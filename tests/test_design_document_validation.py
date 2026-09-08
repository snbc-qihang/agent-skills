from __future__ import annotations
import unittest
from pathlib import Path
from copy import deepcopy
from engineering_assistant.artifact_validation import validate_artifact_payload
from engineering_assistant.design_documents import validate_template
from engineering_assistant.validation import ValidationFailure
ROOT=Path(__file__).resolve().parents[1]

class DesignDocumentValidationTests(unittest.TestCase):
    def package(self):
        return {'requirement_id':'REQ-1','requirement_items':['item-1'],
                'documents':[{'id':role,'role':role,'content':'已记录适用范围与具体结论。','document_status':'reviewing'} for role in ['impact','specialist-diff','implementation-test-plan','change-summary','checklist']]+[
                    {'id':'design','role':'context-design','content':'# Design\n## Behavior\n明确行为及接口变更。\n','document_status':'reviewing','base_document_number':'DES-1','base_version':'1','base_digest':'sha256:'+'a'*64,'template':'# Template\n## Behavior\n正文\n'}],
                'traceability':[{'requirement_item':'item-1','design_document':'design','design_section':'## Behavior','design_change':'新增接口校验','code_targets':['service.validate'],'test_cases':['reject-invalid-input'],'status':'planned'}]}
    def validate(self, package):
        return validate_artifact_payload(schema_root=ROOT/'schemas',kind='review-package',artifact=package)
    def test_complete_package_structure_does_not_grant_approval(self):
        result=self.validate(self.package())
        self.assertEqual('passed',result['status'])
        self.assertEqual('not_verified',result['human_review_status'])
    def test_missing_traceability_and_wrong_section_rejected(self):
        for mode in ['missing','wrong-section','wrong-item']:
            p=self.package()
            if mode=='missing':p['requirement_items'].append('item-2')
            elif mode=='wrong-section':p['traceability'][0]['design_section']='## Missing'
            else:p['traceability'][0]['requirement_item']='invented'
            with self.subTest(mode=mode),self.assertRaises(ValidationFailure):self.validate(p)
    def test_template_and_status_must_hold(self):
        for mode in ['template','status','placeholder','metadata']:
            p=self.package();doc=p['documents'][-1]
            if mode=='template':doc['content']='## Other\n不同内容'
            elif mode=='status':doc['document_status']='approved'
            elif mode=='placeholder':doc['content']+='TODO'
            else:del doc['base_digest']
            with self.subTest(mode=mode),self.assertRaises(ValidationFailure):self.validate(p)
    def test_table_order_and_headers_are_not_keyword_checks(self):
        template='## A\n内容\n| name | type |\n| --- | --- |\n| x | int |\n## B\n内容\n'
        validate_template(template,template)
        with self.assertRaises(ValidationFailure):validate_template(template.replace('| name | type |','| type | name |'),template)
        with self.assertRaises(ValidationFailure):validate_template(template.replace('## B\n内容','## B\n'),template)
    def test_unfilled_database_template_rejected(self):
        text=(ROOT/'skills/codebase-design/references/relational-oltp-detailed-design-template.md').read_text()
        with self.assertRaises(ValidationFailure):validate_artifact_payload(schema_root=ROOT/'schemas',kind='database-design',artifact={'document':text})

    def test_completed_database_template_and_literal_code_braces(self):
        import re
        text=(ROOT/'skills/codebase-design/references/relational-oltp-detailed-design-template.md').read_text()
        text=re.sub(r"\{[^{}\n]+\}","example",text)
        text=text.replace("待填写","已核实").replace("待确认","已核实").replace("待补充","已核实")
        result=validate_artifact_payload(schema_root=ROOT/'schemas',kind='database-design',artifact={'document':text})
        self.assertEqual('passed',result['status'])
        validate_template('## A\n```json\n{"event":"paid"}\n```','## A\n填写内容')

    def test_trace_placeholders_or_non_design_documents_rejected(self):
        for mode in ['placeholder','impact']:
            p=self.package()
            if mode=='placeholder':p['traceability'][0]['test_cases']=['TBD']
            else:
                p['documents'][0]['content']='## Impact\n明确受影响范围。'
                p['traceability'][0]['design_document']='impact'
                p['traceability'][0]['design_section']='## Impact'
            with self.subTest(mode=mode),self.assertRaises(ValidationFailure):self.validate(p)

    def test_table_cannot_move_between_sections(self):
        table='| name | type |\n| --- | --- |\n| x | int |\n'
        template='## A\n内容\n'+table+'## B\n内容\n'
        moved='## A\n内容\n## B\n内容\n'+table
        with self.assertRaises(ValidationFailure):validate_template(moved,template)
