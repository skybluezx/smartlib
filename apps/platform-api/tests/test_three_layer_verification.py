import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_three_layer_publication_verification import (
    author_agreement,
    identifier_association_check,
    layer_status,
    parse_pubmed_article,
)


def test_pubmed_detail_parser_keeps_identifiers_authors_and_lifecycle() -> None:
    article = ET.fromstring(
        """<PubmedArticle>
        <MedlineCitation><PMID>123</PMID><Article>
          <ArticleTitle>Verified title</ArticleTitle>
          <AuthorList><Author><LastName>Smith</LastName><ForeName>Alice</ForeName>
            <Identifier Source="ORCID">0000-0001-0002-0003</Identifier>
            <AffiliationInfo><Affiliation>Example University</Affiliation></AffiliationInfo>
          </Author></AuthorList>
        </Article><CommentsCorrectionsList>
          <CommentsCorrections RefType="RetractionOf"><PMID>122</PMID></CommentsCorrections>
        </CommentsCorrectionsList></MedlineCitation>
        <PubmedData><ArticleIdList>
          <ArticleId IdType="doi">10.1000/test</ArticleId>
          <ArticleId IdType="pmc">PMC123</ArticleId>
        </ArticleIdList></PubmedData>
        </PubmedArticle>"""
    )

    result = parse_pubmed_article(article)

    assert result["pmid"] == "123"
    assert result["pmcid"] == "PMC123"
    assert result["doi"] == "10.1000/test"
    assert result["authors"][0]["orcid"] == "0000-0001-0002-0003"
    assert result["comments_corrections"][0]["type"] == "RetractionOf"


def test_author_agreement_and_blocking_rollup_are_conservative() -> None:
    score, matches = author_agreement(["Alice Smith"], [{"order": 1, "name": "Alice Smith"}])
    assert score == 1.0
    assert matches[0]["candidate_order"] == 1
    assert (
        layer_status(
            [
                {"severity": "blocking", "check_status": "passed"},
                {"severity": "blocking", "check_status": "pending"},
            ],
            True,
        )
        == "incomplete"
    )


def test_identifier_association_checks_each_available_identifier_link() -> None:
    result = identifier_association_check(
        {"doi": "10.1000/test", "pmid": "123", "pmcid": "PMC123"},
        {"doi": "10.1000/test"},
        {"doi": "10.1000/test", "pmid": "123", "pmcid": "PMC123"},
    )

    assert result["check_label"] == "标识符关联校验"
    assert result["check_status"] == "passed"
    comparisons = result["authoritative_value"]["comparisons"]
    assert {item["code"] for item in comparisons} >= {
        "source_crossref_doi",
        "crossref_pubmed_doi",
        "source_pubmed_pmid",
        "source_pubmed_pmcid",
        "pubmed_pmid_pmcid",
    }


def test_identifier_association_rejects_cross_source_conflicts() -> None:
    result = identifier_association_check(
        {"doi": "10.1000/source", "pmid": "123"},
        {"doi": "10.1000/crossref"},
        {"doi": "10.1000/crossref", "pmid": "456"},
    )

    assert result["check_status"] == "conflict"
    assert result["details"]["conflict_count"] == 2
