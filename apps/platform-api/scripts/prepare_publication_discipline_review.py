#!/usr/bin/env python3
# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from smartlib_platform.storage.s3 import S3ObjectStore

METHOD_VERSION = "publication-discipline-fulltext-rules-v1"
SCHEMES = (
    "MOE_GRADUATE_DISCIPLINE_2022",
    "NSFC_APPLICATION_CODE_2026",
    "GBT_13745_2009",
)

# Generic full-text terms are fallback signals; specific topics and title hits drive primaries.
PROFILE_FACTORS = {
    "oncology": 0.72,
    "infection": 0.62,
    "immunology": 0.68,
    "genetics_omics": 0.62,
    "cell_molecular": 0.36,
    "clinical_general": 0.20,
    "basic_biomed": 0.25,
}
ILLEGAL_XML_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class TopicProfile:
    key: str
    label: str
    patterns: tuple[str, ...]
    targets: dict[str, tuple[tuple[str, float], ...]]
    rationale: str


def targets(moe: str, nsfc: str, gbt: str, *, secondary: tuple[str, str, str] | None = None):
    result = {
        SCHEMES[0]: ((moe, 1.0),),
        SCHEMES[1]: ((nsfc, 1.0),),
        SCHEMES[2]: ((gbt, 1.0),),
    }
    if secondary:
        for scheme, code in zip(SCHEMES, secondary, strict=True):
            result[scheme] += ((code, 0.58),)
    return result


PROFILES = (
    TopicProfile(
        "tumor_immunity",
        "肿瘤免疫与免疫治疗",
        (r"immunotherap", r"cancer.immun", r"tumou?r.immun", r"anti[- ]?pd-?1", r"nanovaccine"),
        targets("1001", "H1818", "32067", secondary=("1002", "H1806", "31034")),
        "肿瘤免疫或免疫治疗为主要研究问题",
    ),
    TopicProfile(
        "tumor_stem",
        "肿瘤干细胞",
        (r"cancer stem", r"tumou?r stem", r"stemness"),
        targets("1001", "H1810", "32067", secondary=("0710", "C1201", "31017")),
        "研究肿瘤干性或肿瘤干细胞",
    ),
    TopicProfile(
        "tumor_metastasis",
        "肿瘤侵袭与转移",
        (r"metasta", r"perineural invasion", r"invasive cancer"),
        targets("1001", "H1809", "32067"),
        "研究肿瘤侵袭、转移或远处播散",
    ),
    TopicProfile(
        "tumor_resistance",
        "肿瘤治疗抵抗",
        (r"chemoresistan", r"drug resistan", r"therapy resistan", r"radioresistan"),
        targets("1001", "H1821", "32067"),
        "研究肿瘤治疗耐受或耐药",
    ),
    TopicProfile(
        "tumor_diagnosis",
        "肿瘤诊断与标志物",
        (r"tumou?r marker", r"cancer biomarker", r"pan-cancer", r"prognostic biomarker", r"cancer diagnosis"),
        targets("1002", "H1813", "32067", secondary=("1001", "H1825", "31057")),
        "研究肿瘤诊断、预后标志物或肿瘤数据分析",
    ),
    TopicProfile(
        "oncology",
        "肿瘤学",
        (
            r"cancer",
            r"tumou?r",
            r"carcinoma",
            r"glioblastoma",
            r"melanoma",
            r"leukemia",
            r"lymphoma",
            r"neoplasm",
            r"oncogenic",
            r"anticancer",
            r"antitumor",
        ),
        targets("1001", "H18", "32067", secondary=("1002", "C07", "31017")),
        "全文研究对象为肿瘤发生、进展、诊疗或治疗",
    ),
    TopicProfile(
        "cardiovascular_general",
        "心血管系统综合",
        (
            r"cardiovascular",
            r"cardiomyocyte",
            r"myocardium",
            r"cardiac",
            r"心血管",
            r"心肌",
            r"丙酮酸脱氢酶",
        ),
        targets("1001", "H02", "310", secondary=("1002", "H0202", "32024")),
        "研究心血管系统的结构、功能、疾病或细胞分子调控",
    ),
    TopicProfile(
        "arrhythmia",
        "心律失常",
        (r"atrial fibrillation", r"ventricular arrhythm", r"arrhythmia", r"cardiac electrophysi"),
        targets("1002", "H0204", "32024"),
        "研究心电活动异常或心律失常",
    ),
    TopicProfile(
        "coronary",
        "冠心病与心肌缺血",
        (r"coronary", r"myocardial infarction", r"myocardial isch", r"ischemi[ac].heart", r"cardiotoxic"),
        targets("1002", "H0205", "32024", secondary=("1001", "H0202", "31044")),
        "研究冠状动脉病、心肌缺血或心肌损伤",
    ),
    TopicProfile(
        "heart_failure",
        "心力衰竭与心肌重构",
        (
            r"heart failure",
            r"cardiac hypertrophy",
            r"cardiac remodel",
            r"diastolic dysfunction",
            r"cardiac fibrosis",
        ),
        targets("1002", "H0209", "32024", secondary=("1001", "H0202", "31021")),
        "研究心力衰竭、心肌肥厚、纤维化或重构",
    ),
    TopicProfile(
        "hypertension",
        "高血压",
        (r"hypertension", r"blood pressure"),
        targets("1002", "H0213", "32024"),
        "研究血压调节异常或高血压",
    ),
    TopicProfile(
        "atherosclerosis",
        "动脉粥样硬化与血栓",
        (r"atherosclero", r"thrombo", r"platelet", r"vascular dysfunction"),
        targets("1002", "H0214", "32024", secondary=("1001", "H0212", "31044")),
        "研究动脉粥样硬化、血栓或血管损伤",
    ),
    TopicProfile(
        "vascular",
        "血管结构与功能",
        (r"endothelial", r"vascular remodel", r"angiogenesis", r"blood vessel", r"microvascular"),
        targets("1001", "H0211", "31021", secondary=("0831", "H0212", "41660")),
        "研究血管发生、内皮功能、损伤或重构",
    ),
    TopicProfile(
        "stroke",
        "脑卒中与脑血管病",
        (r"ischemic stroke", r"cardioembolic stroke", r"cerebral isch", r"brain isch", r"stroke"),
        targets("1002", "H0906", "32054"),
        "研究脑卒中或脑血管结构功能异常",
    ),
    TopicProfile(
        "neurodegeneration",
        "神经退行性疾病",
        (r"alzheimer", r"parkinson", r"amyloid", r"aβ", r"neurodegener"),
        targets("1002", "H0912", "32054", secondary=("1001", "C09", "18047")),
        "研究阿尔茨海默病、帕金森病或神经退行性改变",
    ),
    TopicProfile(
        "neuroinflammation",
        "神经炎症与损伤",
        (r"neuroinflamm", r"microglia", r"brain lesion", r"encephalopathy", r"neuronal injury"),
        targets("1001", "H0909", "32054", secondary=("0710", "C09", "18047")),
        "研究神经炎症、胶质细胞或神经损伤",
    ),
    TopicProfile(
        "psychiatry",
        "精神卫生与心理健康",
        (
            r"depressi",
            r"schizophren",
            r"anxiety",
            r"psychological stress",
            r"emotional disturbance",
            r"impulsiv",
            r"抑郁",
            r"精神分裂",
            r"焦虑",
        ),
        targets("1002", "H10", "32057", secondary=("0402", "C09", "19040")),
        "研究精神障碍、情绪、压力或心理健康",
    ),
    TopicProfile(
        "respiratory",
        "呼吸系统",
        (
            r"pulmonary",
            r"lung injury",
            r"respiratory distress",
            r"alveolar",
            r"airway",
            r"pulmonary fibrosis",
            r"肺动脉高压",
            r"肺血管",
            r"缺氧",
        ),
        targets("1002", "H01", "32024"),
        "研究肺、气道或呼吸系统疾病",
    ),
    TopicProfile(
        "ibd_colitis",
        "炎症性肠病与肠道炎症",
        (r"inflammatory bowel", r"colitis", r"intestinal inflammation", r"gut inflammation"),
        targets("1002", "H0302", "32024", secondary=("1001", "H0304", "31034")),
        "研究炎症性肠病、结肠炎或肠黏膜免疫",
    ),
    TopicProfile(
        "pancreatitis",
        "胰腺炎",
        (r"pancreatitis", r"pancreatic injury"),
        targets("1002", "H0313", "32024"),
        "研究胰腺炎及相关器官损伤",
    ),
    TopicProfile(
        "liver",
        "肝脏疾病",
        (r"hepatitis", r"liver fibrosis", r"hepatic", r"hepatocellular", r"cirrhosis", r"fatty liver"),
        targets("1002", "H0309", "32024", secondary=("1001", "H0307", "31044")),
        "研究肝炎、肝纤维化、肝硬化或肝代谢异常",
    ),
    TopicProfile(
        "kidney",
        "肾脏与泌尿系统",
        (r"renal", r"kidney", r"urothelial", r"bladder", r"cystitis", r"prostatitis"),
        targets("1002", "H05", "32024"),
        "研究肾脏、膀胱、尿路或前列腺疾病",
    ),
    TopicProfile(
        "diabetes",
        "糖尿病与糖代谢",
        (r"diabet", r"hyperglyc", r"insulin resistan", r"glucose metabolism"),
        targets("1002", "H0708", "32024", secondary=("1001", "H0707", "31011")),
        "研究糖尿病、糖稳态或胰岛素抵抗",
    ),
    TopicProfile(
        "thyroid",
        "甲状腺疾病",
        (r"thyroid", r"hashimoto"),
        targets("1002", "H0703", "32024"),
        "研究甲状腺及相关免疫或代谢疾病",
    ),
    TopicProfile(
        "obesity_lipid",
        "肥胖与脂质代谢",
        (
            r"\bobes(?:e|ity)\b",
            r"dyslipid",
            r"lipid metabolism",
            r"fatty acid oxidation",
            r"hyperlipid",
        ),
        targets("1001", "H0709", "31011", secondary=("1002", "H0710", "32024")),
        "研究肥胖、脂质代谢或能量代谢异常",
    ),
    TopicProfile(
        "bone_joint",
        "骨与关节疾病",
        (
            r"osteoarth",
            r"osteopor",
            r"osteogen",
            r"osteoblast",
            r"bone repair",
            r"bone loss",
            r"rheumatoid arthritis",
            r"synoviocyte",
        ),
        targets("1002", "H06", "32024", secondary=("1001", "H0604", "31017")),
        "研究骨、关节、软组织损伤、退变或修复",
    ),
    TopicProfile(
        "oral_periodontal",
        "口腔与牙周疾病",
        (r"periodont", r"oral tissue", r"alveolar bone", r"dental", r"tooth"),
        targets("1003", "H1504", "32044", secondary=("0831", "H1502", "41660")),
        "研究牙周、口腔组织或牙槽骨",
    ),
    TopicProfile(
        "regenerative",
        "再生医学与组织工程",
        (
            r"regenerat",
            r"tissue engineering",
            r"organoid",
            r"organ-on-a-chip",
            r"organs-on-chips",
            r"bioengineer",
            r"bioprint",
        ),
        targets("0831", "H28", "41660", secondary=("1001", "C1003", "18021")),
        "研究组织修复、器官芯片、生物工程或再生医学",
    ),
    TopicProfile(
        "medical_ai",
        "医学人工智能与计算方法",
        (
            r"cloud-edge",
            r"\bbert\b",
            r"medical dialogue",
            r"smart medicine",
            r"residual network",
            r"deep learning",
            r"machine learning",
            r"artificial intelligence",
        ),
        targets("0812", "F06", "52020", secondary=("0831", "H2709", "41660")),
        "以人工智能、机器学习或计算系统为主要研究方法与贡献",
    ),
    TopicProfile(
        "medical_imaging_ai",
        "医学影像与人工智能",
        (
            r"medical imag",
            r"mri",
            r"magnetic resonance",
            r"ultrasonograph",
            r"image classification",
            r"survival prediction",
        ),
        targets("0831", "H2709", "41660", secondary=("0812", "F06", "52060")),
        "研究医学影像、医学数据或人工智能方法",
    ),
    TopicProfile(
        "biosensor_probe",
        "生物医学检测与化学测量",
        (
            r"fluorescent probe",
            r"biosensor",
            r"chemosensor",
            r"paper-based sensor",
            r"\bsensor\b",
            r"detection strategy",
            r"bioimaging",
            r"immunoassay",
        ),
        targets("0703", "B04", "15025", secondary=("0831", "H2803", "41660")),
        "研究探针、传感器、分析检测或生物成像",
    ),
    TopicProfile(
        "nanomedicine",
        "纳米医学与生物材料",
        (
            r"nanoparticle",
            r"nanodrug",
            r"nanomaterial",
            r"nanovesicle",
            r"microneedle",
            r"hydrogel",
            r"scaffold",
            r"biomaterial",
            r"nanoimmun",
        ),
        targets("0831", "H2808", "43070", secondary=("0805", "C1002", "43060")),
        "研究纳米递送、生物材料或医学工程材料",
    ),
    TopicProfile(
        "pharmacology",
        "药理学与药物作用",
        (
            r"pharmacolog",
            r"drug response",
            r"drug development",
            r"therapeutic effect",
            r"inhibitor",
            r"agonist",
            r"antagonist",
        ),
        targets("1007", "H35", "31047", secondary=("1001", "H3513", "35040")),
        "研究药物作用、靶点、抑制剂或药效机制",
    ),
    TopicProfile(
        "drug_metabolism",
        "药物代谢与药代动力学",
        (
            r"cytochrome p450",
            r"cyp\d",
            r"ugt1a",
            r"glucuron",
            r"carboxylesterase",
            r"pharmacokinetic",
            r"drug metabolism",
            r"tissue distribution",
        ),
        targets("1007", "H3510", "31047", secondary=("0703", "B0706", "35010")),
        "研究药物代谢酶、药代动力学或体内分布",
    ),
    TopicProfile(
        "natural_tcm",
        "中药与天然产物",
        (
            r"traditional chinese medicine",
            r"decoction",
            r"formula",
            r"natural product",
            r"triterpenoid",
            r"flavone",
            r"alkaloid",
            r"dendrobine",
            r"berberine",
            r"brusatol",
            r"中药",
            r"汤",
            r"方剂",
        ),
        targets("1008", "H32", "36040", secondary=("1007", "H3402", "35010")),
        "研究中药复方、天然产物或天然药物化学",
    ),
    TopicProfile(
        "microbiome",
        "微生物组与肠道微生态",
        (
            r"microbiom",
            r"gut dysbios",
            r"gut fung",
            r"intestinal fung",
            r"mycobiome",
            r"gut virome",
            r"gut microbiota",
        ),
        targets("0710", "C0103", "18061", secondary=("1001", "H0304", "31041")),
        "研究微生物组、肠道真菌或肠道病毒群",
    ),
    TopicProfile(
        "infection",
        "病原生物与感染",
        (r"infection", r"virus", r"viral", r"bacteri", r"fungal", r"pathogen", r"hepatitis b"),
        targets("1001", "H22", "31041", secondary=("0710", "C01", "18061")),
        "研究病原微生物、病毒或感染过程",
    ),
    TopicProfile(
        "immunology",
        "免疫学",
        (r"immune", r"immunolog", r"macrophage", r"t lymphocyte", r"b cell", r"cytokine", r"inflammasome"),
        targets("1001", "H11", "31034", secondary=("0710", "C08", "18021")),
        "研究免疫应答、免疫细胞或炎症调控",
    ),
    TopicProfile(
        "genetics_omics",
        "遗传学与多组学",
        (
            r"genome",
            r"genetic",
            r"rna-seq",
            r"transcriptom",
            r"proteom",
            r"multi-omics",
            r"methylation",
            r"m6a",
        ),
        targets("0710", "C06", "18037", secondary=("1001", "H23", "31027")),
        "研究遗传变异、表观遗传或组学分析",
    ),
    TopicProfile(
        "cell_molecular",
        "细胞与分子生物学",
        (
            r"signaling pathway",
            r"cell proliferation",
            r"apoptosis",
            r"autophagy",
            r"ferroptosis",
            r"mitochond",
            r"protein",
            r"transcription factor",
            r"cellular",
        ),
        targets("0710", "C07", "18021", secondary=("1001", "C21", "18037")),
        "研究细胞命运、信号通路或分子调控",
    ),
    TopicProfile(
        "biochemistry_structure",
        "生物化学与结构生物学",
        (
            r"crystal structure",
            r"structural and biochemical",
            r"enzyme activity",
            r"lipase",
            r"protein structure",
            r"molecular interaction",
        ),
        targets("0710", "C05", "18017", secondary=("0703", "B07", "15060")),
        "研究蛋白质结构、酶功能或生物化学机制",
    ),
    TopicProfile(
        "biomechanics",
        "生物力学",
        (r"mechanobiolog", r"biomechan", r"single-molecule", r"force-dependent", r"matrix stiffness"),
        targets("0831", "A10", "13041", secondary=("0710", "C05", "18014")),
        "研究力学作用下的生物结构与功能",
    ),
    TopicProfile(
        "public_health",
        "公共卫生与流行病学",
        (
            r"cross-sectional",
            r"cohort",
            r"risk factor",
            r"epidemiolog",
            r"public health",
            r"population",
            r"prevalence",
        ),
        targets("1004", "H30", "33021", secondary=("0714", "H3011", "91060")),
        "研究人群分布、风险因素、流行病学或公共卫生",
    ),
    TopicProfile(
        "nursing",
        "护理学与支持照护",
        (
            r"nursing",
            r"supportive care",
            r"self-perceived burden",
            r"illness acceptance",
            r"family caring",
            r"护理",
            r"支持性照顾",
            r"照护",
        ),
        targets("1011", "H30", "32071", secondary=("1004", "H3013", "33077")),
        "研究护理干预、支持照护或患者体验",
    ),
    TopicProfile(
        "rehabilitation",
        "康复医学",
        (
            r"rehabilitation",
            r"exercise intervention",
            r"low back pain",
            r"core stability",
            r"physical therapy",
            r"m-health",
        ),
        targets("1002", "H20", "32017"),
        "研究康复、运动干预或理疗",
    ),
    TopicProfile(
        "toxicology_environment",
        "毒理与环境健康",
        (
            r"toxicity",
            r"toxicology",
            r"arsenic",
            r"pollutant",
            r"pesticide",
            r"paraquat",
            r"environmental exposure",
        ),
        targets("1004", "B0607", "33014", secondary=("0703", "B06", "61020")),
        "研究环境暴露、污染物或毒理效应",
    ),
    TopicProfile(
        "clinical_general",
        "临床医学综合",
        (
            r"patients?",
            r"clinical trial",
            r"randomi[sz]ed",
            r"clinical outcome",
            r"prognostic",
            r"case-control",
            r"retrospective",
        ),
        targets("1002", "H16", "320", secondary=("1004", "H30", "33021")),
        "研究对象和证据主要来自临床患者或临床试验",
    ),
    TopicProfile(
        "basic_biomed",
        "基础医学综合",
        (r"\bmice\b", r"\bmouse\b", r"in vivo", r"in vitro", r"cell line", r"mechanism", r"pathway"),
        targets("1001", "C11", "310", secondary=("0710", "C21", "18037")),
        "以实验模型、细胞和机制研究为主",
    ),
)


def normalize(value: str | None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", text).strip().lower()


def field_hits(pattern: str, fields: dict[str, str]) -> list[tuple[str, str]]:
    hits = []
    for field, value in fields.items():
        match = re.search(pattern, value, re.I)
        if match:
            hits.append((field, match.group(0)))
    return hits


def excerpt(text: str, terms: list[str], radius: int = 120) -> str:
    lowered = text.lower()
    positions = [
        (lowered.find(term.lower()), term) for term in terms if term and lowered.find(term.lower()) >= 0
    ]
    if not positions:
        return text[:240].strip()
    position, _ = min(positions)
    start = max(position - radius, 0)
    end = min(position + radius, len(text))
    return re.sub(r"\s+", " ", text[start:end]).strip()


def classify(
    metadata: dict[str, Any], fulltext: str, taxonomy: dict[tuple[str, str], dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attributes = metadata.get("attributes") or {}
    keywords = attributes.get("keywords") if isinstance(attributes.get("keywords"), list) else []
    mesh = attributes.get("mesh_terms") if isinstance(attributes.get("mesh_terms"), list) else []
    fields = {
        "题名": normalize(metadata.get("title")),
        "关键词/MeSH": normalize("; ".join(str(value) for value in [*keywords, *mesh])),
        "摘要": normalize(metadata.get("abstract")),
        "全文前部": normalize(fulltext[:40000]),
    }
    weights = {"题名": 12.0, "关键词/MeSH": 8.0, "摘要": 4.0, "全文前部": 1.0}
    candidate_scores: dict[tuple[str, str], float] = defaultdict(float)
    candidate_signals: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    candidate_rationales: dict[tuple[str, str], set[str]] = defaultdict(set)
    profile_scores: dict[str, float] = {}

    for profile in PROFILES:
        profile_score = 0.0
        profile_signals: list[tuple[str, str]] = []
        for pattern in profile.patterns:
            hits = field_hits(pattern, fields)
            for field, term in hits:
                profile_score += weights[field]
                profile_signals.append((field, term))
        if profile_score == 0:
            continue
        profile_score *= PROFILE_FACTORS.get(profile.key, 1.0)
        profile_scores[profile.key] = profile_score
        for scheme, mapped in profile.targets.items():
            for code, multiplier in mapped:
                key = (scheme, code)
                candidate_scores[key] += profile_score * multiplier
                candidate_rationales[key].add(profile.rationale)
                for field, term in profile_signals:
                    signal = {"field": field, "term": term, "profile": profile.label}
                    if signal not in candidate_signals[key]:
                        candidate_signals[key].append(signal)

    candidates: list[dict[str, Any]] = []
    primary_by_scheme: dict[str, dict[str, Any]] = {}
    for scheme in SCHEMES:
        ranked = sorted(
            ((key, score) for key, score in candidate_scores.items() if key[0] == scheme),
            key=lambda item: (-item[1], item[0][1]),
        )[:3]
        if not ranked:
            continue
        for rank, ((_, code), score) in enumerate(ranked, 1):
            target = taxonomy[(scheme, code)]
            runner_score = ranked[1][1] if rank == 1 and len(ranked) > 1 else 0.0
            margin = score - runner_score if rank == 1 else 0.0
            title_signal = any(signal["field"] == "题名" for signal in candidate_signals[(scheme, code)])
            if score >= 24 and (margin >= 5 or title_signal):
                confidence = "高"
                confidence_value = min(0.97, 0.72 + score / 300)
            elif score >= 9:
                confidence = "中"
                confidence_value = min(0.84, 0.52 + score / 350)
            else:
                confidence = "低"
                confidence_value = min(0.64, 0.38 + score / 250)
            matched_terms = list(
                dict.fromkeys(signal["term"] for signal in candidate_signals[(scheme, code)])
            )
            item = {
                "scheme": scheme,
                "rank": rank,
                "discipline_object_id": target["object_id"],
                "code": code,
                "name": target["canonical_name"],
                "level": target["level"],
                "score": round(score, 2),
                "confidence": confidence,
                "confidence_value": round(confidence_value, 4),
                "matched_terms": matched_terms[:12],
                "signal_fields": sorted({signal["field"] for signal in candidate_signals[(scheme, code)]}),
                "rationale": "；".join(sorted(candidate_rationales[(scheme, code)])),
                "evidence_excerpt": excerpt(fulltext, matched_terms),
                "method_version": METHOD_VERSION,
            }
            candidates.append(item)
            if rank == 1:
                primary_by_scheme[scheme] = item

    missing_schemes = [scheme for scheme in SCHEMES if scheme not in primary_by_scheme]
    low_schemes = [scheme for scheme, item in primary_by_scheme.items() if item["confidence"] == "低"]
    review_status = (
        "建议确认"
        if not missing_schemes
        and not low_schemes
        and sum(item["confidence"] == "高" for item in primary_by_scheme.values()) >= 2
        else "需人工判断"
    )
    summary = {
        "review_status": review_status,
        "missing_schemes": missing_schemes,
        "low_confidence_schemes": low_schemes,
        "matched_profiles": sorted(profile_scores, key=profile_scores.get, reverse=True)[:8],
        "primary_by_scheme": primary_by_scheme,
    }
    return candidates, summary


def fetch_publications(connection: psycopg.Connection) -> list[dict[str, Any]]:
    return list(
        connection.execute(
            """SELECT meta.publication_id::text,meta.title,meta.abstract,meta.journal_name,
                      meta.publication_year,meta.attributes,
                      array_agg(COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)
                       ORDER BY COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)) AS source_rows,
                      array_agg(
                          submission.representative_work_number
                       ORDER BY COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)
                      ) AS work_numbers,
                      array_agg(submission.awardee_name_raw
                       ORDER BY COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)) AS awardees,
                      resource.fulltext_resource_id::text,resource.storage_uri,
                      resource.extracted_text_uri,resource.content_checksum,resource.text_length,
                      resource.page_count,resource.extraction_method
                 FROM smartlib.publication_metadata meta
                 JOIN (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
                   ON item.matched_publication_id=meta.publication_id
                 JOIN LATERAL (
                      SELECT fulltext.* FROM smartlib.publication_fulltext_resource fulltext
                       WHERE fulltext.publication_id=meta.publication_id
                       ORDER BY fulltext.created_at DESC LIMIT 1
                 ) resource ON true
                GROUP BY meta.publication_id,meta.title,meta.abstract,meta.journal_name,
                         meta.publication_year,meta.attributes,resource.fulltext_resource_id,
                         resource.storage_uri,resource.extracted_text_uri,resource.content_checksum,
                         resource.text_length,resource.page_count,resource.extraction_method
                ORDER BY min(COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer))"""
        ).fetchall()
    )


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {
                key: ILLEGAL_XML_CONTROL_RE.sub(" ", value) if isinstance(value, str) else value
                for key, value in row.items()
            }
            for row in rows
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="读取全部正式全文并生成三套学科体系候选关系")
    parser.add_argument("--taxonomy-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = json.loads(args.taxonomy_package.read_text(encoding="utf-8"))
    taxonomy = {
        (item["scheme"], item["code"]): item
        for item in package["objects"]
        if item["object_type"] == "discipline"
    }
    referenced_codes = {
        (scheme, code)
        for profile in PROFILES
        for scheme, mapped in profile.targets.items()
        for code, _ in mapped
    }
    if missing_codes := referenced_codes - set(taxonomy):
        raise ValueError(f"规则引用了不存在的学科代码: {sorted(missing_codes)}")

    store = S3ObjectStore(
        os.environ["SMARTLIB_S3_ENDPOINT_URL"],
        os.environ["SMARTLIB_S3_BUCKET"],
        os.environ["SMARTLIB_S3_ACCESS_KEY"],
        os.environ["SMARTLIB_S3_SECRET_KEY"],
        os.environ.get("SMARTLIB_S3_REGION", "us-east-1"),
        httpx.Client(timeout=httpx.Timeout(90, connect=10)),
    )
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute(
            "SELECT set_config('smartlib.actor_id', %s, true)",
            (os.environ["SMARTLIB_DEV_ACTOR_ID"],),
        )
        publications = fetch_publications(connection)

    results = []
    all_candidates = []
    read_failures = []
    for publication in publications:
        text_uri = publication["extracted_text_uri"]
        try:
            key = str(text_uri).split(f"s3://{store.bucket}/", 1)[1]
            fulltext = store.get_bytes(key).decode("utf-8", errors="replace")
        except (IndexError, OSError, UnicodeError, httpx.HTTPError) as exc:
            read_failures.append({"publication_id": publication["publication_id"], "error": str(exc)})
            continue
        candidates, summary = classify(publication, fulltext, taxonomy)
        result = {
            **publication,
            "fulltext_read_bytes": len(fulltext.encode("utf-8")),
            "fulltext_read_chars": len(fulltext),
            "classification": summary,
            "candidates": candidates,
        }
        results.append(result)
        for candidate in candidates:
            all_candidates.append(
                {
                    "publication_id": publication["publication_id"],
                    "representative_work_numbers": publication["work_numbers"],
                    "title": publication["title"],
                    **candidate,
                }
            )

    if len(publications) != 271 or len(results) != 271 or read_failures:
        raise ValueError(
            "全文范围对账失败: "
            f"publications={len(publications)}, read={len(results)}, failures={read_failures}"
        )
    generated_at = datetime.now(UTC).isoformat()
    status_counts = Counter(result["classification"]["review_status"] for result in results)
    confidence_counts = Counter(
        candidate["confidence"] for candidate in all_candidates if candidate["rank"] == 1
    )
    primary_scheme_counts = {
        scheme: Counter(
            candidate["code"]
            for candidate in all_candidates
            if candidate["scheme"] == scheme and candidate["rank"] == 1
        )
        for scheme in SCHEMES
    }
    output = {
        "manifest": {
            "generated_at": generated_at,
            "method_version": METHOD_VERSION,
            "source_import_rows": 283,
            "unique_publications": len(publications),
            "fulltexts_read": len(results),
            "candidate_relations": len(all_candidates),
            "review_status_counts": dict(status_counts),
            "primary_confidence_counts": dict(confidence_counts),
            "taxonomy_dataset_version": package["manifest"]["dataset_version"],
            "database_write_state": "preview_only_not_applied",
            "important_note": (
                "候选关系由题名、摘要、关键词/MeSH和全文前部规则匹配产生，确认前未写入relation_assertion。"
            ),
        },
        "primary_scheme_counts": {scheme: dict(counts) for scheme, counts in primary_scheme_counts.items()},
        "publications": results,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "论文全文学科对应_待确认.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    summary_rows = [
        {"项目": "原始论文记录", "数量": 283, "说明": "受控导入批次"},
        {"项目": "唯一正式论文对象", "数量": len(publications), "说明": "重复记录合并后"},
        {"项目": "成功读取全文", "数量": len(results), "说明": "读取MinIO解析文本"},
        {"项目": "候选关系", "数量": len(all_candidates), "说明": "每体系最多3个候选"},
        {
            "项目": "建议确认",
            "数量": status_counts.get("建议确认", 0),
            "说明": "三个体系均有候选且至少两个主候选为高置信",
        },
        {
            "项目": "需人工判断",
            "数量": status_counts.get("需人工判断", 0),
            "说明": "低置信、候选接近或跨学科",
        },
    ]
    write_csv(args.output / "00_汇总.csv", summary_rows, ["项目", "数量", "说明"])

    review_rows = []
    for result in results:
        primary = result["classification"]["primary_by_scheme"]
        for source_row, work_number, awardee in zip(
            result["source_rows"], result["work_numbers"], result["awardees"], strict=True
        ):
            row = {
                "源行": source_row,
                "代表作编号": work_number,
                "获批人": awardee,
                "论文对象ID": result["publication_id"],
                "题名": result["title"],
                "年份": result["publication_year"],
                "期刊": result["journal_name"],
                "全文字符数": result["fulltext_read_chars"],
                "整体建议": result["classification"]["review_status"],
            }
            for scheme, prefix in zip(SCHEMES, ("教育部", "国自然", "GB_T"), strict=True):
                item = primary.get(scheme, {})
                row[f"{prefix}代码"] = item.get("code", "")
                row[f"{prefix}名称"] = item.get("name", "")
                row[f"{prefix}置信度"] = item.get("confidence", "")
                row[f"{prefix}依据"] = item.get("rationale", "")
            review_rows.append(row)
    review_columns = [
        "源行",
        "代表作编号",
        "获批人",
        "论文对象ID",
        "题名",
        "年份",
        "期刊",
        "全文字符数",
        "教育部代码",
        "教育部名称",
        "教育部置信度",
        "教育部依据",
        "国自然代码",
        "国自然名称",
        "国自然置信度",
        "国自然依据",
        "GB_T代码",
        "GB_T名称",
        "GB_T置信度",
        "GB_T依据",
        "整体建议",
    ]
    write_csv(args.output / "01_283条论文主建议.csv", review_rows, review_columns)

    detail_rows = []
    scheme_labels = {SCHEMES[0]: "教育部", SCHEMES[1]: "国自然", SCHEMES[2]: "GB/T"}
    for item in all_candidates:
        detail_rows.append(
            {
                "论文对象ID": item["publication_id"],
                "代表作编号": ";".join(item["representative_work_numbers"]),
                "题名": item["title"],
                "体系": scheme_labels[item["scheme"]],
                "候选顺位": item["rank"],
                "学科对象ID": item["discipline_object_id"],
                "代码": item["code"],
                "名称": item["name"],
                "层级": item["level"],
                "置信度": item["confidence"],
                "置信值": item["confidence_value"],
                "得分": item["score"],
                "命中位置": ";".join(item["signal_fields"]),
                "命中词": ";".join(item["matched_terms"]),
                "判断依据": item["rationale"],
                "全文证据片段": item["evidence_excerpt"],
            }
        )
    detail_columns = [
        "论文对象ID",
        "代表作编号",
        "题名",
        "体系",
        "候选顺位",
        "学科对象ID",
        "代码",
        "名称",
        "层级",
        "置信度",
        "置信值",
        "得分",
        "命中位置",
        "命中词",
        "判断依据",
        "全文证据片段",
    ]
    write_csv(args.output / "02_候选关系明细.csv", detail_rows, detail_columns)
    uncertain_ids = {
        result["publication_id"]
        for result in results
        if result["classification"]["review_status"] == "需人工判断"
    }
    write_csv(
        args.output / "03_低置信与待确认.csv",
        [row for row in review_rows if row["论文对象ID"] in uncertain_ids],
        review_columns,
    )
    rule_rows = [
        {
            "规则标识": profile.key,
            "主题": profile.label,
            "匹配表达": ";".join(profile.patterns),
            "教育部目标": ";".join(code for code, _ in profile.targets[SCHEMES[0]]),
            "国自然目标": ";".join(code for code, _ in profile.targets[SCHEMES[1]]),
            "GB_T目标": ";".join(code for code, _ in profile.targets[SCHEMES[2]]),
            "解释": profile.rationale,
        }
        for profile in PROFILES
    ]
    write_csv(
        args.output / "04_分类规则说明.csv",
        rule_rows,
        ["规则标识", "主题", "匹配表达", "教育部目标", "国自然目标", "GB_T目标", "解释"],
    )
    print(json.dumps(output["manifest"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
