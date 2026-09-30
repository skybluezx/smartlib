"""HTTP endpoints retain the existing application permission and transaction boundary."""
import os
from typing import Annotated
from uuid import UUID
from fastapi import Depends, HTTPException, UploadFile, File
from pydantic import ValidationError
from . import research_workbench as w
from .research_standards import StandardPackage, import_package
from .research_profiles import load_profiles
from smartlib_platform.storage.s3 import S3ObjectStore

from .research_models import ScopedResearchAnalysis, ScopedResearchResult


def register(app,database,Context,request_context,require_permission):
    def execute(context,permission,fn):
        if permission:require_permission(context,permission)
        try:
            with database.transaction(context.actor_id) as c:
                return fn(c)
        except LookupError as e:raise HTTPException(404,str(e)) from e
        except (ValueError,ValidationError) as e:raise HTTPException(422,str(e)) from e

    @app.get('/api/v1/research/workspace',tags=['research'])
    def workspace(context:Annotated[Context,Depends(request_context)]):
        def read(c):
            profiles=load_profiles(c)
            standards=c.execute("""SELECT attributes->>'scheme' scheme,attributes->>'scheme_version' version,count(*) count
              FROM smartlib.knowledge_object WHERE attributes->>'standard_library'='research-classification'
              AND system_to='infinity' AND review_state='approved' GROUP BY 1,2 ORDER BY 1,2""").fetchall()
            return {'papers':w.objects(c,'publication'),'entities':[{'id':k,'name':p['name'],'kind':p['object_type']} for k,p in profiles.items() if p['object_type'] in {'person','organization'}],
              'projects':w.projects(c,profiles),'standards':standards,'tasks':w.task_list(c),
              'gaps':([] if any(x['scheme']=='MOE_GRADUATE_DISCIPLINE' for x in standards) else ['缺少教育部学科目录：上传已按官方文件核对的版本化目录；不能自动等同于国自然代码']),
              'scope':'当前可访问的已导入论文，不代表全校全部成果；新增论文自动进入分类队列'}
        return execute(context,'knowledge_hub.read',read)

    @app.get('/api/v1/research/analysis',tags=['research'])
    def analysis(context:Annotated[Context,Depends(request_context)],entity_id:UUID|None=None,start_year:int|None=None,end_year:int|None=None,collaboration_institution_id:UUID|None=None):
        if start_year is not None and end_year is not None and start_year>end_year:raise HTTPException(422,'起始年份不能大于结束年份')
        return execute(context,None,lambda c:w.analytics(load_profiles(c,start_year=start_year,end_year=end_year),str(entity_id) if entity_id else None,
            w.collaboration_members(c,collaboration_institution_id) if collaboration_institution_id else None))

    @app.post('/api/v1/research/scoped-analysis', tags=['research'], response_model=ScopedResearchResult, operation_id='get_scoped_research_analysis')
    def scoped_analysis(command:ScopedResearchAnalysis,context:Annotated[Context,Depends(request_context)]):
        return execute(context,None,lambda c:w.analytics(
            load_profiles(c,publication_ids=command.publication_ids),
            collaboration_memberships=w.collaboration_members(c,command.collaboration_institution_id) if command.collaboration_institution_id else None,
            scheme=command.scheme,scheme_version=command.scheme_version))

    @app.get('/api/v1/research/entities',tags=['research'])
    def entities(context:Annotated[Context,Depends(request_context)]):
        return execute(context,None,lambda c:[{'id':x['id'],'name':x['name'],'kind':kind} for kind in ['person','organization'] for x in w.objects(c,kind)])

    @app.get('/api/v1/research/standards',tags=['research'])
    def standards(context:Annotated[Context,Depends(request_context)],scheme:str|None=None,q:str='',version:str|None=None,parent:str|None=None):
        return execute(context,'knowledge_hub.read',lambda c:w.standards(c,scheme,q,version,parent))

    @app.post('/api/v1/research/generate',tags=['research'])
    def generate(command:w.Generate,context:Annotated[Context,Depends(request_context)]):
        return execute(context,'change.submit',lambda c:w.generate(c,command,context.actor_id))

    @app.post('/api/v1/research/proposals',tags=['research'])
    def proposal(command:w.Proposal,context:Annotated[Context,Depends(request_context)]):
        return execute(context,'change.submit',lambda c:w.propose(c,command,context.actor_id))

    @app.post('/api/v1/research/decisions',tags=['research'])
    def decide(command:w.BatchDecision,context:Annotated[Context,Depends(request_context)]):
        return execute(context,'change.decide',lambda c:w.decide(c,command,context.actor_id))

    @app.post('/api/v1/research/standards/moe',tags=['research'])
    async def upload(context:Annotated[Context,Depends(request_context)],file:UploadFile=File(...)):
        require_permission(context,'change.decide')
        raw=await file.read(5_000_001)
        if len(raw)>5_000_000:raise HTTPException(413,'目录文件上限5MB')
        try:p=StandardPackage.model_validate_json(raw)
        except ValueError as e:raise HTTPException(422,'目录JSON格式错误：'+str(e)) from e
        store=S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],'smartlib-reference-data',os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
        return execute(context,'change.decide',lambda c:import_package(c,p,raw,store,context.actor_id))
