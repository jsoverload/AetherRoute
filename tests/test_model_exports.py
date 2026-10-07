"""Selected resources in vision exports and exact database response identities."""
from pathlib import Path
import sys
import unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model_routes import context, accept_response, prompt_for
from map_visuals import COLORS, model_image, resource_legend
from security import ValidationError

class ModelExportTests(unittest.TestCase):
    def setUp(self):
        self.image=Image.new('RGB',(240,160),'#263247')
        self.resources=[dict(X=40,Y=50,Kind='Crystal',Name='Amethyst',Id='gem',Source='Imported map database'),
                        dict(X=160,Y=100,Kind='Plant',Name='Odyle',Id='od',Source='Imported map database')]
        self.task=context('test-map',self.image.size,[],True,mode='image',kinds=['Crystal','Plant'],resources=self.resources)
    def response(self,entries,task=None):
        task=task or self.task
        return dict(format='aion2-image-path-v1',reference=task['reference'],request_id=task['request_id'],nodes=entries)
    def test_empty_route_still_exports_visible_resources_with_original_geometry(self):
        original=self.image.tobytes();annotated=model_image(self.image,self.task)
        self.assertEqual(annotated.size,self.image.size)
        self.assertEqual(annotated.getpixel((40,50)),(195,161,255))
        self.assertEqual(annotated.getpixel((160,100)),(101,239,161))
        self.assertEqual(annotated.getpixel((100,75)),self.image.getpixel((100,75)))  # no invented path
        self.assertEqual(self.image.tobytes(),original)
        self.assertEqual(self.task['candidates'],[])
        self.assertEqual(len(self.task['resources']),2)
        self.assertIn('ResourceId',prompt_for(self.task))
        self.assertEqual(resource_legend(self.task)['Crystal']['shape'],'diamond')
    def test_known_resource_ids_restore_exact_metadata_and_allow_waypoints(self):
        entries=[dict(ResourceId=self.task['resources'][1]['ResourceId']),dict(X=100,Y=75,Kind='Waypoint'),dict(ResourceId=self.task['resources'][0]['ResourceId'])]
        nodes=accept_response(self.response(entries),self.task)
        self.assertEqual(nodes[0],self.resources[1]);self.assertEqual(nodes[2],self.resources[0])
        self.assertEqual(nodes[1]['Kind'],'Waypoint')
        self.assertEqual(nodes[1]['Source'],'Model image proposal (unverified)')
    def test_resource_response_rejects_unknown_duplicate_and_overrides(self):
        rid=self.task['resources'][0]['ResourceId']
        for entries in ([dict(ResourceId='unknown')],[dict(ResourceId=[])],
                        [dict(ResourceId=rid),dict(ResourceId=rid)],
                        [dict(ResourceId=rid,X=10)],[dict(ResourceId=rid,Kind='Ore')],
                        [dict(ResourceId=rid,Name='Invented')],[dict(ResourceId=rid,StopId='stop-0001')]):
            with self.subTest(entries=entries),self.assertRaises(ValidationError):accept_response(self.response(entries),self.task)
    def test_candidate_and_resource_alias_cannot_duplicate_same_stop(self):
        task=context('test-map',self.image.size,[self.resources[0]],True,mode='image',kinds=['Crystal','Plant'],resources=self.resources)
        rid=task['resources'][0]['ResourceId'];sid=task['candidates'][0]['StopId']
        for entries in ([dict(StopId=sid),dict(ResourceId=rid)],[dict(ResourceId=rid),dict(StopId=sid)]):
            with self.assertRaises(ValidationError):accept_response(self.response(entries,task),task)
        self.assertEqual(accept_response(self.response([dict(ResourceId=rid)],task),task),[self.resources[0]])
    def test_required_candidate_order_remains_enforced(self):
        task=context('test-map',self.image.size,self.resources,True,mode='image',kinds=['Crystal','Plant'],resources=self.resources)
        entries=[dict(ResourceId=n['ResourceId']) for n in reversed(task['resources'])]
        with self.assertRaises(ValidationError):accept_response(self.response(entries,task),task)
        entries.reverse();self.assertEqual(accept_response(self.response(entries,task),task),self.resources)
    def test_same_position_records_keep_their_distinct_resource_identity(self):
        records=[self.resources[0],dict(self.resources[0],Name='Different gem',Id='other-gem')]
        task=context('test-map',self.image.size,records,True,mode='image',kinds=['Crystal'],resources=records)
        self.assertEqual([n['StopId'] for n in task['resources']],['stop-0001','stop-0002'])
        entries=[dict(ResourceId=n['ResourceId']) for n in task['resources']]
        self.assertEqual(accept_response(self.response(entries,task),task),records)
    def test_selection_changes_bind_the_task_and_exclude_other_types(self):
        task=context('test-map',self.image.size,[],True,mode='image',kinds=['Crystal'],resources=self.resources[:1])
        self.assertNotEqual(task['request_id'],self.task['request_id'])
        annotated=model_image(self.image,task)
        self.assertEqual(annotated.getpixel((160,100)),self.image.getpixel((160,100)))
        with self.assertRaises(ValidationError):context('test-map',self.image.size,[],True,mode='image',kinds=['Crystal'],resources=self.resources)
        with self.assertRaises(ValidationError):accept_response(self.response([dict(ResourceId=self.task['resources'][0]['ResourceId'])]),task)
    def test_whole_map_resource_context_does_not_require_over_1000_stops(self):
        resources=[dict(X=i%240,Y=i%160,Kind='Crystal',Id=str(i)) for i in range(1240)]
        task=context('test-map',self.image.size,[],True,mode='image',kinds=['Crystal'],resources=resources)
        self.assertEqual(len(task['resources']),1240)
        self.assertEqual(len(accept_response(self.response([dict(ResourceId=task['resources'][1239]['ResourceId'])],task),task)),1)
        task=context('test-map',self.image.size,resources,True,allow_subset=True,mode='image',kinds=['Crystal'],resources=resources)
        self.assertEqual(len(task['candidates']),1240)
        with self.assertRaises(ValidationError):accept_response(self.response([dict(StopId=n['StopId']) for n in task['candidates']],task),task)
    def test_older_exported_tasks_and_responses_still_work(self):
        task=context('old-map',self.image.size,self.resources,True)
        self.assertNotIn('resources',task)
        data=dict(format='aion2-route-plan-v1',reference=task['reference'],request_id=task['request_id'],stop_ids=[n['StopId'] for n in task['candidates']])
        self.assertEqual(accept_response(data,task),self.resources)
        old_image=context('old-map',self.image.size,[],True,mode='image')
        self.assertEqual(accept_response(self.response([dict(X=30,Y=40,Kind='Crystal')],old_image),old_image)[0]['Kind'],'Crystal')

if __name__=='__main__':unittest.main()
