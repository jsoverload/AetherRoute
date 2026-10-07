"""Map-data conversion and persistence using generated, freely shareable fixtures."""
import base64
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from map_data import KNOWN_IMAGES, MapLibrary, bounds, catalog, create_profile, from_exports, select_nodes, validate_pack, world_to_pixel, world_choices
from profiles import ProfileStore, load_image
from security import ValidationError, atomic_json


def fixture():
    image=Image.new('RGB',(400,300),'#263247');image.putpixel((20,30),(70,90,120))
    data=io.BytesIO();image.save(data,format='PNG')
    pack=dict(format='aetherroute-map-v1',name='Test world',world_id='1110',image=base64.b64encode(data.getvalue()).decode(),
              world_bounds=[-100,-100,100,100],flip_y=True,
              markers=[dict(world=[0,0],Kind='Crystal',Name='Amethyst',Id='gem-1'),dict(world=[50,50],Kind='Plant',Name='Odyle',Id='od-1'),dict(world=[-50,-50],Kind='Ore',Name='Iron',Id='ore-1')],
              regions=[dict(name='Northern area',label=[0,50],polygons=[[[-100,0],[100,0],[100,100],[-100,100]]])])
    return validate_pack(pack)


class MapDataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.pack,self.image=fixture()
    def tearDown(self):self.temp.cleanup()
    def store(self):
        assets=self.root/'assets';assets.mkdir(exist_ok=True);self.image.save(assets/'reference.png')
        atomic_json(assets/'starter-nodes.json',[]);atomic_json(assets/'seed.json',dict(welcome=True,name='Welcome'))
        return ProfileStore(self.root/'profiles',assets)
    def test_world_coordinate_edges_and_y_flip(self):
        self.assertEqual(world_to_pixel([-100,100],self.pack['world_bounds'],self.image.size),(0,0))
        self.assertEqual(world_to_pixel([100,-100],self.pack['world_bounds'],self.image.size),(400,300))
        self.assertEqual(world_to_pixel([-100,-100],self.pack['world_bounds'],self.image.size,False),(0,0))
        nodes,outside=catalog(self.pack,self.image.size)
        self.assertEqual(outside,0);self.assertEqual((nodes[0]['X'],nodes[0]['Y']),(200,150))
    def test_missing_bounds_never_guess_positions(self):
        self.pack['world_bounds']=None
        with self.assertRaises(ValidationError):catalog(self.pack,self.image.size)
        normalized,_=validate_pack(self.pack)
        self.assertIsNone(normalized['world_bounds'])  # Same world, different image.
    def test_verified_image_alignment_and_existing_pack_upgrade(self):
        self.pack['world_bounds']=None;self.pack['flip_y']=False
        with patch('map_data.reference_id',return_value=KNOWN_IMAGES['1110'][0]):
            pack,image=validate_pack(self.pack)
            self.assertEqual(pack['world_bounds'],[-408000,-408000,408000,408000])
            self.assertTrue(pack['flip_y'])
            library=MapLibrary(self.root/'maps');entry=library.add(pack)
            atomic_json(library.file(entry),self.pack)  # Pack saved by the previous release.
            reloaded,_=library.load(entry)
            self.assertEqual(reloaded['world_bounds'],pack['world_bounds'])
            nodes,outside=catalog(reloaded,image.size)
            self.assertEqual((len(nodes),outside),(3,0))
    def test_verified_image_does_not_override_explicit_bounds_or_other_worlds(self):
        with patch('map_data.reference_id',return_value=KNOWN_IMAGES['1110'][0]):
            normalized,_=validate_pack(self.pack)
            self.assertEqual(normalized['world_bounds'],self.pack['world_bounds'])
            self.pack['world_id']='1010';self.pack['world_bounds']=None
            normalized,_=validate_pack(self.pack)
            self.assertIsNone(normalized['world_bounds'])
    def test_altgard_projection_matches_sector_configuration(self):
        # Independent projection: 8 sectors, 102000 game units and 1024 tiles
        # per sector; the tile plane is scaled to the complete decoded image.
        size=(2048,2048);boundary=KNOWN_IMAGES['1110'][1]
        for x,y in ((-408000,408000),(408000,-408000),(0,0),
                    (-67399.9296875,156482.78125),(209982.71875,230069.0625)):
            tile_x=(x+408000)*8192/816000
            tile_y=(408000-y)*8192/816000
            px,py=world_to_pixel((x,y),boundary,size)
            self.assertAlmostEqual(px,tile_x*size[0]/8192)
            self.assertAlmostEqual(py,tile_y*size[1]/8192)
    def test_invalid_bounds_and_coordinates(self):
        for value in ([0,0,0,10],[0,0,10,-1],[True,0,10,10],[0,0,float('nan'),1]):
            with self.subTest(value=value),self.assertRaises(ValidationError):bounds(value)
        for change in ({'world':[float('inf'),0]},{'Kind':'Waypoint'},{'Name':'bad\0name'}):
            pack=copy.deepcopy(self.pack);pack['markers'][0].update(change)
            with self.assertRaises(ValidationError):validate_pack(pack)
    def test_duplicate_marker_ids_rejected(self):
        self.pack['markers'][1]['Id']='gem-1'
        with self.assertRaises(ValidationError):validate_pack(self.pack)
    def test_crop_preserves_types_and_clean_terrain(self):
        store=self.store();nodes,_=catalog(self.pack,self.image.size)
        zone=create_profile(store,self.pack,self.image,(100,50,350,250),nodes,[nodes[1]],'Selected area')
        self.assertEqual(len(store.profiles),2);self.assertEqual(len(zone['catalog']),3)
        self.assertEqual(zone['routes'][0]['nodes'][0]['Kind'],'Plant')
        self.assertEqual(zone['routes'][0]['nodes'][0]['Name'],'Odyle')
        self.assertEqual((zone['routes'][0]['nodes'][0]['X'],zone['routes'][0]['nodes'][0]['Y']),(200,25))
        self.assertEqual(load_image(store.image_path(zone)).tobytes(),self.image.crop((100,50,350,250)).tobytes())
        reopened=ProfileStore(store.folder,self.root/'assets')
        self.assertEqual(reopened.active['catalog'][0]['Kind'],'Crystal')
    def test_crop_excluding_a_route_stop_leaves_store_unchanged(self):
        store=self.store();nodes,_=catalog(self.pack,self.image.size);before=store.path.read_bytes()
        with self.assertRaises(ValidationError):create_profile(store,self.pack,self.image,(0,0,100,100),nodes,[nodes[1]],'Bad crop')
        self.assertEqual(len(store.profiles),1);self.assertEqual(store.path.read_bytes(),before)
    def test_filter_name_type_and_polygon(self):
        nodes,_=catalog(self.pack,self.image.size)
        self.assertEqual(select_nodes(nodes,{'Crystal'},'AMETHYST')[0]['Id'],'gem-1')
        self.assertEqual(select_nodes(nodes,{'Plant'},'iron'),[])
        polygon=[[(0,0),(400,0),(400,100),(0,100)]]
        self.assertEqual([n['Id'] for n in select_nodes(nodes,{'Plant','Ore'},region=polygon)],['od-1'])
    def test_outside_markers_are_reported(self):
        self.pack['markers'][0]['world']=[1000,1000]
        nodes,outside=catalog(self.pack,self.image.size)
        self.assertEqual(outside,1);self.assertEqual(len(nodes),2)
    def test_library_roundtrip_and_double_delete_storage(self):
        library=MapLibrary(self.root/'maps');entry=library.add(self.pack)
        reopened=MapLibrary(library.folder);pack,image=reopened.load(reopened.entries[0])
        self.assertEqual(pack['markers'],self.pack['markers']);self.assertEqual(image.size,self.image.size)
        reopened.delete(entry);self.assertEqual(MapLibrary(library.folder).entries,[])
        self.assertTrue(reopened.file(entry).exists())  # recovery copy only
    def test_failed_profile_save_rolls_back_catalog_and_image(self):
        store=self.store();nodes,_=catalog(self.pack,self.image.size)
        with patch.object(store,'write',side_effect=OSError('full disk')):
            with self.assertRaises(OSError):create_profile(store,self.pack,self.image,(0,0,400,300),nodes,nodes,'Failed')
        self.assertEqual(len(store.profiles),1);self.assertEqual(len(list((store.folder/'profile-images').glob('*.png'))),1)
    def test_raw_export_world_and_type_selection(self):
        image=self.root/'map.png';self.image.save(image)
        records=[dict(id='gem',name='Amethyst',mapWorldId='1110',mapType='gatherable',mapCategory='jewelry',coordinates=[[0,0]]),
                 dict(id='cube',name='Hidden Cube',mapWorldId='1110',mapType='collectable',mapCategory='hidden-cube',coordinates=[[5,5]]),
                 dict(id='monster',name='Beast',mapWorldId='1110',mapType='monster',mapCategory='feral',coordinates=[[3,3]]),
                 dict(id='foreign',name='Od',mapWorldId='1010',mapType='gatherable',mapCategory='od',coordinates=[[0,0]])]
        markers=self.root/'getMarkers.json';atomic_json(markers,{'result':{'data':records}})
        pack=from_exports(image,markers,None,'1110','Altgard fixture')
        self.assertEqual([m['Kind'] for m in pack['markers']],['Crystal','HiddenCube'])
        self.assertIsNone(pack['world_bounds']);self.assertEqual(dict(world_choices(markers)),{'1110':2,'1010':1})
    def test_private_image_metadata_and_unknown_fields_are_not_shared(self):
        image=self.image.copy();exif=Image.Exif();exif[270]='private-location';out=io.BytesIO();image.save(out,format='PNG',exif=exif)
        self.pack['image']=base64.b64encode(out.getvalue()).decode();self.pack['private_token']='secret'
        normalized,clean=validate_pack(self.pack)
        self.assertNotIn('private_token',normalized);self.assertFalse(clean.info)
        with Image.open(io.BytesIO(base64.b64decode(normalized['image']))) as stored:self.assertFalse(stored.info)


if __name__=='__main__':unittest.main()
