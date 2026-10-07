"""Resource glyphs for the editor and annotated, original-size model images."""
import math
from PIL import Image, ImageDraw
from routes import NAMES
from security import plain_image

BG='#141b28';FG='#e7edf5';PANEL='#263247';ROUTE='#40dbf1'

COLORS={'Ore':'#ff8b73','Crystal':'#c3a1ff','Plant':'#65efa1','Custom':'#59dff6','Herbs':'#9ae68a','Trees':'#b79a70','Berries':'#fa8fba','Vegetables':'#e9d875','Shellfish':'#87bcea','HiddenCube':'#ff8b73','Waypoint':'#dce6ef'}
SHAPES={kind:('diamond' if kind=='Crystal' else 'star' if kind=='Plant' else 'square with C' if kind=='HiddenCube' else 'square' if kind=='Ore' else 'circle with initial') for kind in NAMES}

def draw_marker(draw,x,y,kind,size=6):
    color=COLORS[kind];outline='#13202c'
    if kind in ('Ore','HiddenCube'):
        draw.rectangle((x-size,y-size,x+size,y+size),fill=color,outline=outline,width=2)
        if kind=='HiddenCube':draw.text((x,y),'C',fill=outline,anchor='mm')
    elif kind=='Crystal':
        draw.polygon(((x,y-size-2),(x+size,y),(x,y+size+2),(x-size,y)),fill=color,outline=outline,width=2)
    elif kind=='Plant':
        points=[]
        for j in range(10):
            angle=math.pi*j/5-math.pi/2;radius=size+2 if j%2==0 else size*.45
            points.append((x+math.cos(angle)*radius,y+math.sin(angle)*radius))
        draw.polygon(points,fill=color,outline=outline,width=2)
    else:
        draw.ellipse((x-size,y-size,x+size,y+size),fill=color,outline=outline,width=2)
        draw.text((x,y),NAMES[kind][0],fill=outline,anchor='mm')

def model_image(image,request):
    # Draw only on a copy. The tracking reference and its coordinate system stay
    # intact; resource dots are candidates, never a precomputed connecting path.
    result=plain_image(image);draw=ImageDraw.Draw(result)
    for node in request.get('resources',[]):draw_marker(draw,node['X'],node['Y'],node['Kind'])
    for i,node in enumerate(request['candidates']):
        x,y=node['X'],node['Y'];draw_marker(draw,x,y,node['Kind'])
        draw.ellipse((x-10,y-10,x+10,y+10),outline='#f5fbff',width=2)
        draw.text((x+11,y-11),str(i+1),fill='#f5fbff',stroke_width=1,stroke_fill='#13202c')
    return result

def resource_legend(request):
    kinds={n['Kind'] for n in request.get('resources',[])+request['candidates']}
    return {kind:dict(name=NAMES[kind],color=COLORS[kind],shape=SHAPES[kind]) for kind in NAMES if kind in kinds}

def legend_image(request):
    legend=resource_legend(request);image=Image.new('RGB',(480,max(100,60+len(legend)*32)),'#141b28');draw=ImageDraw.Draw(image)
    draw.text((16,14),'Map resources (not a visit order)',fill='#e7edf5')
    for i,(kind,item) in enumerate(legend.items()):
        y=50+i*32;draw_marker(draw,26,y,kind)
        draw.text((48,y-7),item['name']+' - '+item['shape'],fill='#e7edf5')
    return image
