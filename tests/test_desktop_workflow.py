"""New world/profile workflow regressions without screen capture or user data."""
import copy
import hashlib
import ctypes
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_map_data import fixture
from map_data import catalog, create_profile, validate_pack
from profiles import ProfileStore, profile_source, reference_id
from security import ValidationError, atomic_json, read_json
from world_maps import built_in_maps, load_built_in
from ui_settings import Preferences, clean_settings
from desktop_ui import GameLauncher, launcher_position
from product import DATA_FOLDER, NAME
from app import RouteEditor
from routes import connect_nodes

ROOT=Path(__file__).resolve().parents[1]

class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.pack,self.image=fixture()
        assets=self.root/'assets';assets.mkdir();self.image.save(assets/'reference.png')
        atomic_json(assets/'seed.json',dict(welcome=True,name='Welcome'))
        atomic_json(assets/'starter-nodes.json',[])
        self.store=ProfileStore(self.root/'data',assets)
    def tearDown(self):self.temp.cleanup()

    def test_origin_roundtrip_keeps_separate_libraries_and_old_routes(self):
        original=copy.deepcopy(self.store.active)
        nodes,_=catalog(self.pack,self.image.size)
        interactive=create_profile(self.store,self.pack,self.image,(80,50,350,250),nodes,nodes[:1],'Database zone')
        picture=self.store.create('Picture zone',self.image)
        self.assertEqual(profile_source(interactive),'interactive')
        self.assertEqual(profile_source(picture),'picture')
        self.assertEqual(interactive['map_world'],'1110')
        self.assertEqual(interactive['map_name'],'Test world')
        path=self.root/'shared.json';self.store.export(interactive,path)
        shared=read_json(path)['profile']
        self.assertNotIn('app-settings',str(shared))
        imported=self.store.import_file(path)
        self.assertEqual(profile_source(imported),'interactive')
        self.assertEqual(imported['routes'][0]['nodes'],interactive['routes'][0]['nodes'])
        reopened=ProfileStore(self.store.folder,self.root/'assets')
        groups={kind:[p['name'] for p in reopened.profiles if profile_source(p)==kind] for kind in ('picture','interactive')}
        self.assertEqual(groups['picture'],['Picture zone'])
        self.assertEqual(groups['interactive'],['Database zone','Database zone'])
        self.assertEqual(reopened.profiles[0]['routes'],original['routes'])

    def test_older_database_and_picture_profiles_are_grouped_without_rewriting(self):
        nodes,_=catalog(self.pack,self.image.size)
        zone=create_profile(self.store,self.pack,self.image,(0,0,*self.image.size),nodes,[],'Old database')
        for key in ('zone_source','map_world','map_name'):zone.pop(key,None)
        picture=self.store.create('Old picture',self.image);picture.pop('zone_source')
        self.store.write();raw=self.store.path.read_bytes()
        reopened=ProfileStore(self.store.folder,self.root/'assets')
        self.assertEqual(profile_source(reopened.profiles[1]),'interactive')
        self.assertEqual(profile_source(reopened.profiles[2]),'picture')
        self.assertEqual(reopened.path.read_bytes(),raw)

    def test_bad_origin_rejected_before_creating_files_or_importing(self):
        before=self.store.path.read_bytes();images=list((self.store.folder/'profile-images').iterdir())
        with self.assertRaises(ValidationError):self.store.create('Invalid',self.image,zone_source='remote-script')
        path=self.root/'shared.json';self.store.export(self.store.active,path)
        data=read_json(path);data['profile']['zone_source']='invalid';atomic_json(path,data)
        with self.assertRaises(ValidationError):self.store.import_file(path)
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertEqual(list((self.store.folder/'profile-images').iterdir()),images)

    def test_rename_preserves_pixel_namespace_and_saved_folder(self):
        digest=hashlib.sha256(b'WayveilRGB-v1\0'+struct.pack('<II',*self.image.size)+self.image.tobytes()).hexdigest()[:24]
        self.assertEqual(reference_id(self.image),'map-px-'+digest)
        self.assertEqual(DATA_FOLDER,'Aion2RouteSync');self.assertEqual(NAME,'AetherRoute')
        legacy=dict(self.pack,format='wayveil-map-v1')
        normalized,_=validate_pack(legacy)
        self.assertEqual(normalized['format'],'aetherroute-map-v1')

    def test_all_bundled_worlds_are_complete_and_within_the_map(self):
        entries=built_in_maps(ROOT)
        expected={'1110':('Altgard',4063,72),'1010':('Verteron',4173,71)}
        self.assertEqual({e['world_id'] for e in entries},set(expected))
        for entry in entries:
            with self.subTest(world=entry['world_id']):
                pack,image=load_built_in(ROOT,entry);nodes,outside=catalog(pack,image.size)
                self.assertEqual((pack['name'],len(nodes),len(pack['regions'])),expected[entry['world_id']])
                self.assertEqual(outside,0);self.assertEqual(image.size,(2048,2048))
                self.assertEqual(pack['world_bounds'],[-408000,-408000,408000,408000])

    def test_map_index_rejects_traversal_duplicates_and_missing_metadata(self):
        folder=self.root/'maps';folder.mkdir()
        entry=dict(name='World',world_id='1110',file='world.map.json',sha256='a'*64)
        for data in ([dict(entry,file='../private.map.json')],[entry,entry],[dict(entry,sha256='')],[dict(entry,world_id='')]):
            with self.subTest(data=data):
                atomic_json(folder/'index.json',data)
                with self.assertRaises(ValidationError):built_in_maps(self.root)

    def test_modified_bundled_pack_is_rejected_before_use(self):
        folder=self.root/'maps';folder.mkdir();path=folder/'test.map.json'
        atomic_json(path,self.pack)
        atomic_json(folder/'index.json',[dict(name=self.pack['name'],world_id='1110',file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
        entry=built_in_maps(self.root)[0];load_built_in(self.root,entry)
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValidationError,'incomplete or modified'):load_built_in(self.root,entry)

    def test_preferences_survive_restart_and_failed_save(self):
        preferences=Preferences(self.root/'settings')
        self.assertFalse(preferences.data['developer_mode']);self.assertTrue(preferences.data['start_collapsed'])
        preferences.update(developer_mode=True,launcher_margin=[40,60],last_map='builtin-1010')
        reopened=Preferences(self.root/'settings');before=copy.deepcopy(reopened.data)
        self.assertEqual(reopened.data,preferences.data)
        with patch('ui_settings.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):reopened.update(launcher_enabled=False)
        self.assertEqual(reopened.data,before);self.assertEqual(Preferences(self.root/'settings').data,before)

    def test_settings_strict_types_and_unknown_values_omitted(self):
        for data in (dict(developer_mode='false'),dict(start_collapsed=1),dict(launcher_margin=[True,1]),dict(launcher_margin=[-1,0]),dict(launcher_margin=[10001,1])):
            with self.subTest(data=data),self.assertRaises(ValidationError):clean_settings(data)
        self.assertNotIn('api_key',clean_settings(dict(api_key='secret')))

    def test_launcher_position_supports_secondary_and_small_screens(self):
        self.assertEqual(launcher_position((0,0,1920,1080),(178,48),[18,36]),(1724,996))
        self.assertEqual(launcher_position((-1920,-200,1920,1080),(178,48),[18,36]),(-196,796))
        self.assertEqual(launcher_position((40,30,100,20),(178,48),[18,36]),(40,30))

class ConnectNodesTests(unittest.TestCase):
    def node(self,identity,x,y=0,kind='Crystal',**extra):
        return dict(X=x,Y=y,Kind=kind,Id=identity,Name=identity,Source='Imported map database',**extra)
    def editor(self,nodes,catalog,filters=None):
        editor=RouteEditor.__new__(RouteEditor)
        editor.app=SimpleNamespace(nodes=copy.deepcopy(nodes),catalog=copy.deepcopy(catalog),
            filters={kind:Mock(get=Mock(return_value=enabled)) for kind,enabled in (filters or {}).items()},
            next_node=4,route_changed=Mock())
        editor.history=[];editor.selected=0;editor.hint=Mock();editor.window=Mock()
        return editor

    def test_one_click_respects_filters_preserves_manual_stops_and_undoes_together(self):
        manual=dict(X=10,Y=20,Kind='Waypoint',Name='Bridge',Source='Manual marker')
        visited=self.node('visited',30)
        far=self.node('far',100);near=self.node('near',31);hidden=self.node('ore',32,kind='Ore')
        original=[manual,visited]
        editor=self.editor(original,[visited,far,near,hidden],{'Crystal':True,'Ore':False})
        catalog_before=copy.deepcopy(editor.app.catalog)
        editor.connect_all()
        self.assertEqual(editor.app.nodes[:2],original)
        self.assertEqual([n['Id'] for n in editor.app.nodes[2:]],['near','far'])
        self.assertEqual(editor.app.nodes[2],near)
        self.assertEqual(editor.app.catalog,catalog_before)
        self.assertEqual(len(editor.history),1)
        self.assertIsNone(editor.selected);self.assertEqual(editor.app.next_node,0)
        editor.app.route_changed.assert_called_once_with()
        editor.undo()
        self.assertEqual(editor.app.nodes,original);self.assertEqual(editor.history,[])
        self.assertEqual(editor.app.route_changed.call_count,2)

    def test_repeat_click_does_not_duplicate_nodes_or_create_an_undo_step(self):
        editor=self.editor([],[self.node('a',0),self.node('b',10),self.node('a',0)])
        editor.connect_all();before=copy.deepcopy(editor.app.nodes)
        editor.connect_all()
        self.assertEqual(editor.app.nodes,before);self.assertEqual(len(before),2)
        self.assertEqual(len(editor.history),1)
        editor.app.route_changed.assert_called_once_with()

    def test_distinct_resource_ids_at_one_position_survive_connection(self):
        first=self.node('a',10);second=self.node('b',10)
        connected=connect_nodes([],[first,second,first])
        self.assertEqual(connected,[first,second])
        manual=dict(X=10,Y=0,Kind='Crystal',Name='My existing stop',Source='Manual marker')
        connected=connect_nodes([manual],[first,second,first])
        self.assertEqual(connected,[manual,second])
        self.assertEqual(connect_nodes(connected,[first,second]),connected)

    def test_catalog_without_ids_matches_position_and_type_without_retyping(self):
        manual=dict(X=10,Y=5,Kind='Plant',Name='Manual Od',Source='Manual marker')
        catalog=[dict(X=10,Y=5,Kind='Plant'),dict(X=10,Y=5,Kind='Crystal'),dict(X=10,Y=5,Kind='Crystal')]
        connected=connect_nodes([manual],catalog)
        self.assertEqual(connected,[manual,catalog[1]])
        connected[1]['Name']='Route-only edit'
        self.assertNotIn('Name',catalog[1])

    def test_limit_rejection_keeps_route_selection_history_and_save_untouched(self):
        nodes=[self.node('n'+str(i),i%100,i//100) for i in range(1000)]
        editor=self.editor(nodes,[self.node('extra',1,1)])
        with patch('app.messagebox.showinfo') as notice:editor.connect_all()
        self.assertEqual(editor.app.nodes,nodes);self.assertEqual(editor.history,[])
        self.assertEqual(editor.selected,0);self.assertEqual(editor.app.next_node,4)
        editor.app.route_changed.assert_not_called()
        notice.assert_called_once()
        self.assertIn('No stops were added',notice.call_args.args[1])
        self.assertEqual(len(connect_nodes([],nodes)),1000)

    def test_empty_picture_or_unselected_types_do_not_change_the_route(self):
        for catalog,filters in (([],{}),([self.node('a',5)],{'Crystal':False})):
            editor=self.editor([],catalog,filters)
            editor.connect_all()
            self.assertEqual(editor.app.nodes,[]);self.assertEqual(editor.history,[])
            editor.app.route_changed.assert_not_called()
            self.assertIn('No resource nodes',editor.hint.set.call_args.args[0])

class WindowsSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.api=Mock();self.api.GetAncestor.return_value=123
        self.api.GetWindowLongW.return_value=0
        self.widget=Mock();self.widget.winfo_id.return_value=123
        spec=importlib.util.spec_from_file_location('windows_contract',ROOT/'windows.py')
        self.module=importlib.util.module_from_spec(spec)
        with patch.object(ctypes,'WinDLL',return_value=self.api,create=True):spec.loader.exec_module(self.module)
    def test_launcher_remains_clickable_and_does_not_activate(self):
        self.module.launcher_styles(self.widget)
        style=self.api.SetWindowLongW.call_args.args[2]
        self.assertTrue(style&0x08000000)  # WS_EX_NOACTIVATE
        self.assertTrue(style&0x80)  # WS_EX_TOOLWINDOW
        self.assertFalse(style&0x20)  # WS_EX_TRANSPARENT would block clicks
        self.assertTrue(self.api.SetWindowPos.call_args.args[-1]&0x10)
        self.api.SetWindowDisplayAffinity.assert_called_once_with(123,0x11)
    def test_native_position_uses_absolute_negative_monitor_coordinates(self):
        self.module.position_window(self.widget,-196,-120,178,48)
        call=self.api.SetWindowPos.call_args.args
        self.assertEqual(call[2:],(-196,-120,178,48,0x10))
        self.widget.update_idletasks.assert_called_once()
        self.api.SetForegroundWindow.assert_not_called()
    def test_show_launcher_avoids_foreground_activation(self):
        self.module.show_without_activation(self.widget)
        self.api.ShowWindow.assert_called_once_with(123,4)
        self.assertTrue(self.api.SetWindowPos.call_args.args[-1]&0x10)
        self.api.SetForegroundWindow.assert_not_called()

class LauncherFocusTests(unittest.TestCase):
    def setUp(self):
        self.native=Mock();self.native.window_exists.return_value=True
        self.native.foreground.return_value=123
        self.native.client_region.return_value=dict(left=-1920,top=40,width=1920,height=1040)
        self.native.monitor_work_area.return_value=(0,0,1920,1040)
        self.native.root_handle.return_value=456
        self.launcher=GameLauncher.__new__(GameLauncher)
        self.launcher.app=SimpleNamespace(target=123,demo=None,root=Mock(),status=Mock())
    def bounds(self):
        with patch('desktop_ui.sys.platform','win32'),patch.dict(sys.modules,{'windows':self.native}):return self.launcher.bounds()
    def test_foreground_game_supplies_its_client_bounds(self):
        self.assertEqual(self.bounds(),(-1920,40,1920,1040))
    def test_unfocused_or_minimized_game_hides_badge(self):
        self.native.foreground.return_value=999
        self.assertIsNone(self.bounds())
        self.native.foreground.return_value=123;self.native.client_region.return_value=None
        self.assertIsNone(self.bounds())
    def test_closed_game_returns_launcher_to_desktop_and_allows_rebinding(self):
        self.native.window_exists.return_value=False
        self.assertEqual(self.bounds(),(0,0,1920,1040))
        self.assertIsNone(self.launcher.app.target)
        self.launcher.app.status.set.assert_called_once()

if __name__=='__main__':unittest.main()
