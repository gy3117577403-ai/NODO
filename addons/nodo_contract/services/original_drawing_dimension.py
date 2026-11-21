# Private engine adapter from Jingneng sales c3c120987925ec1b4f417f6c3d398b7f7ce9e6ce.
import json, os, pathlib, socket, sys, re
payload = json.load(sys.stdin)
os.environ.update(QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1",
                  OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
def no_network(*args, **kwargs):
    raise OSError("Local drawing recognition has no network access")
socket.create_connection = no_network
socket.socket.connect = no_network
client = pathlib.Path(payload["client"])
bundle = pathlib.Path(payload["bundle"])
sys.path.insert(0, str(client))
sys.path.extend([payload["dependencies"], str(bundle), payload["pure_dependencies"]])
handles = [os.add_dll_directory(str(path)) for path in (bundle, bundle / "onnxruntime/capi")
           if hasattr(os, "add_dll_directory") and path.is_dir()]
os.environ["AI_QUOTE_V3_CORE_ROOT"] = str(client/"v3_core")
os.environ.pop("AIQUOTE_EDOCR2_PYTHON", None)
os.environ.pop("AIQUOTE_EDOCR2_SOURCE", None)
os.environ.pop("AIQUOTE_EDOCR2_MODEL", None)
os.environ.pop("AIQUOTE_MLSD_TINY_MODEL", None)
if payload.get("converter"):
    os.environ["AIQUOTE_ODA_CONVERTER"] = payload["converter"]
import v3_launcher
original_finder = v3_launcher._OriginalPyzFinder
class LocalBundleFinder(original_finder):
    def __init__(self, archive_path):
        super().__init__(archive_path)
        self.bundle_root = bundle
v3_launcher._OriginalPyzFinder = LocalBundleFinder
if "ezdxf" in sys.modules and not hasattr(sys.modules["ezdxf"], "readfile"):
    for name in list(sys.modules):
        if name == "ezdxf" or name.startswith("ezdxf."):
            del sys.modules[name]
core = v3_launcher.load_v3_namespace()
tools = core["DrawingRecognitionTools"]
renderer = pathlib.Path(payload["renderer"])
if renderer.is_file():
    tools._find_pdftoppm = staticmethod(lambda: str(renderer))
from scheme2_ui import _Scheme2PageRecognitionWorker
from recognition_dimensions import dimension_review_hint
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import onnxruntime as ort
original_session_init = ort.InferenceSession.__init__
def bounded_session(session, model, sess_options=None, *args, **kwargs):
    options = sess_options if sess_options is not None else ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    original_session_init(session, model, options, *args, **kwargs)
ort.InferenceSession.__init__ = bounded_session



import re, subprocess, typing
import cv2
import numpy as np
import PIL._typing
# The shipped OCR renderer imports Pillow type aliases newer than Odoo's Pillow.
# These aliases are only annotations; image decoding below stays inside OpenCV.
if not hasattr(PIL._typing, "Coords"):
    PIL._typing.Coords = typing.Sequence[float]
if not hasattr(PIL._typing, "StrOrBytesPath"):
    PIL._typing.StrOrBytesPath = typing.Union[str, bytes, os.PathLike]
source = pathlib.Path(payload["path"])
page_number = payload["page"]
rotation = payload["rotation"]
orientation=payload.get("orientation",0)
display_rotation=rotation
rotation=(rotation-orientation)%360
click_point = list(payload["point"])
u,v = click_point
if rotation == 90: payload["point"] = [v,1-u]
elif rotation == 180: payload["point"] = [1-u,1-v]
elif rotation == 270: payload["point"] = [1-v,u]
manual_rect=payload.get("rect")
if manual_rect:
    a,b,c,d=manual_rect
    if rotation==90:manual_rect=[b,1-a-c,d,c]
    elif rotation==180:manual_rect=[1-a-c,1-b-d,c,d]
    elif rotation==270:manual_rect=[1-b-d,a,d,c]
pdf_page = None
if source.suffix.lower() == ".pdf":
    from pypdf import PdfReader
    reader = PdfReader(str(source))
    pdf_page = reader.pages[page_number-1]
    image_path = source.parent / "dimension-page"
    rendered = subprocess.run([payload["renderer"], "-f", str(page_number), "-l", str(page_number),
        "-singlefile", "-cropbox", "-scale-to", "2400", "-png", str(source), str(image_path)],
        capture_output=True, timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if rendered.returncode:
        raise ValueError("无法渲染当前 PDF 页")
    content = image_path.with_suffix(".png").read_bytes()
else:
    content = source.read_bytes()
image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
if image is None:
    raise ValueError("无法读取当前图纸")
if orientation:
    image=cv2.rotate(image,{90:cv2.ROTATE_90_CLOCKWISE,180:cv2.ROTATE_180,270:cv2.ROTATE_90_COUNTERCLOCKWISE}[orientation])
height, width = image.shape[:2]
if max(width, height) > 2400:
    ratio = 2400 / max(width, height)
    image = cv2.resize(image, (round(width*ratio), round(height*ratio)))
height, width = image.shape[:2]
px, py = payload["point"][0]*width, payload["point"][1]*height
gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
ink = cv2.bitwise_or(ink,cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,9))
closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8))
contours, hierarchy = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
rectangles = []
cores = []
for contour in contours:
    x,y,w,h = cv2.boundingRect(contour)
    if w < max(20,width*.025) or h < max(25,height*.035) or w*h > width*height*.55:
        continue
    if x <= 2 and x+w >= width-2 or y <= 2 and y+h >= height-2:
        continue
    approximation=cv2.approxPolyDP(contour,cv2.arcLength(contour,True)*.01,True)
    if cv2.contourArea(contour)/(w*h) < .90 or len(approximation)>8 or not cv2.isContourConvex(approximation):
        continue
    if any(abs(x-a[0])+abs(y-a[1])+abs(w-a[2])+abs(h-a[3]) < 15 for a in cores):
        continue
    cores.append((x,y,w,h))
    if not (x-3 <= px <= x+w+3 and y-3 <= py <= y+h+3):
        continue
    rectangles.append((x,y,w,h))
if manual_rect:
    mx,my,mw,mh=manual_rect
    left=max(0,round(mx*width));top=max(0,round(my*height))
    right=min(width,round((mx+mw)*width));bottom=min(height,round((my+mh)*height))
    # Contours help associate labels with cabinet edges, but never change the
    # user-drawn selection or read labels outside it.
    cores=[r for r in cores if r[0]>=left and r[1]>=top and r[0]+r[2]<=right and r[1]+r[3]<=bottom]
    rectangles=[r for r in rectangles if r[0]>=left and r[1]>=top and r[0]+r[2]<=right and r[1]+r[3]<=bottom]
    if not rectangles:
        # Recover an open contour from four connected straight cabinet edges.
        vm=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(20,round(height*.035)),1),np.uint8))
        hm=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(20,round(width*.025))),np.uint8))
        vertical=[];horizontal=[]
        for c in cv2.findContours(vm,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            a,b,cw,ch=cv2.boundingRect(c)
            if b-3<=py<=b+ch+3:vertical.append((a+cw/2,b,b+ch))
        for c in cv2.findContours(hm,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            a,b,cw,ch=cv2.boundingRect(c);horizontal.append((b+ch/2,a,a+cw))
        le=sorted([v for v in vertical if v[0]<=px],key=lambda v:px-v[0])[:12]
        ri=sorted([v for v in vertical if v[0]>=px],key=lambda v:v[0]-px)[:12]
        for l in le:
            for r in ri:
                a,b=l[0],max(l[1],r[1]);cw,ch=r[0]-a,min(l[2],r[2])-b
                if cw<max(20,width*.025) or ch<max(25,height*.035) or cw*ch>width*height*.55:continue
                tolerance=max(5,ch*.02)
                tops=[p for p,u,v in horizontal if b-tolerance<=p<=py and u<=a+5 and v>=a+cw-5]
                bottoms=[p for p,u,v in horizontal if py<=p<=b+ch+tolerance and u<=a+5 and v>=a+cw-5]
                if tops and bottoms:
                    y0,y1=max(tops),min(bottoms)
                    if y1-y0>=max(25,height*.035):rectangles.append(tuple(round(v) for v in (a,y0,cw,y1-y0)))
        if rectangles:rectangles=[min(rectangles,key=lambda r:r[2]*r[3])]
    rectangles=[r for r in rectangles if r[0]>=left and r[1]>=top and r[0]+r[2]<=right and r[1]+r[3]<=bottom]
    if cores or rectangles:
        x,y,w,h=max(rectangles or cores,key=lambda r:r[2]*r[3])
        for _ in range(8):
            before=(x,y,w,h)
            for a,b,c,d in cores:
                if abs(b-y)<max(5,h*.035) and abs(b+d-y-h)<max(5,h*.035) and a<=x+w+max(6,w*.06) and a+c>=x-max(6,w*.06):
                    nx,ny=min(x,a),min(y,b)
                    w,h=max(x+w,a+c)-nx,max(y+h,b+d)-ny;x,y=nx,ny
            if before==(x,y,w,h):break
        # A handle cut-out can open one door's contour. Match the continuous paired
        # cabinet edges beside the clicked interior to include both doors in that case.
        for horizontal in (True,):
            span=w if horizontal else h
            mask=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(15,round(span*.6))) if horizontal else (max(15,round(span*.6)),1),np.uint8))
            edges=[]
            for c in cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
                a,b,cw,ch=cv2.boundingRect(c)
                pos,start,end=(b+ch/2,a,a+cw) if horizontal else (a+cw/2,b,b+ch)
                origin=x if horizontal else y
                if start<=origin+span*.1 and end>=origin+span*.9:edges.append((pos,start,end))
            low,high=(y,y+h) if horizontal else (x,x+w)
            tolerance=max(5,(h if horizontal else w)*.035)
            first=sorted([e for e in edges if abs(e[0]-low)<=tolerance],key=lambda e:abs(e[0]-low))
            last=sorted([e for e in edges if abs(e[0]-high)<=tolerance],key=lambda e:abs(e[0]-high))
            if first and last:
                begin=max(first[0][1],last[0][1]);end=min(first[0][2],last[0][2])
                if span<=end-begin<=span*4:
                    if horizontal:x,w=round(begin),round(end-begin)
                    else:y,h=round(begin),round(end-begin)
        # Snap the joined interiors to nearby cabinet edges, excluding the more distant
        # dimension-line rectangle which used to enlarge the entire selected view.
        def nearby_edges(horizontal):
            length=max(15,round((w if horizontal else h)*.65))
            mask=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,length) if horizontal else (length,1),np.uint8))
            found=[]
            for c in cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
                a,b,cw,ch=cv2.boundingRect(c)
                if horizontal and cw>=w*.65 and a<=x+w*.15 and a+cw>=x+w*.85:found.append(b+ch/2)
                elif not horizontal and ch>=h*.65 and b<=y+h*.15 and b+ch>=y+h*.85:found.append(a+cw/2)
            return found
        horizontal_edges,vertical_edges=nearby_edges(True),nearby_edges(False)
        oldx,oldy,oldright,oldbottom=x,y,x+w,y+h
        frame_band=max(8,min(w,h)*.07)
        xs=[v for v in vertical_edges if oldx-frame_band<=v<=oldx+2]
        xe=[v for v in vertical_edges if oldright-2<=v<=oldright+frame_band]
        ys=[v for v in horizontal_edges if oldy-frame_band<=v<=oldy+2]
        ye=[v for v in horizontal_edges if oldbottom-2<=v<=oldbottom+frame_band]
        x=round(min(xs,default=oldx));y=round(min(ys,default=oldy))
        w=round(max(xe,default=oldright))-x;h=round(max(ye,default=oldbottom))-y
        x=max(left,x);y=max(top,y)
        w=min(right-x,w);h=min(bottom-y,h)
        body=(x,y,w,h)
    else:
        body=(left,top,right-left,bottom-top)
    x,y,w,h=body
else:
    if not rectangles:
        # Recover an open contour from four connected straight cabinet edges.
        vm=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(20,round(height*.035)),1),np.uint8))
        hm=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(20,round(width*.025))),np.uint8))
        vertical=[];horizontal=[]
        for c in cv2.findContours(vm,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            a,b,cw,ch=cv2.boundingRect(c)
            if b-3<=py<=b+ch+3:vertical.append((a+cw/2,b,b+ch))
        for c in cv2.findContours(hm,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            a,b,cw,ch=cv2.boundingRect(c);horizontal.append((b+ch/2,a,a+cw))
        le=sorted([v for v in vertical if v[0]<=px],key=lambda v:px-v[0])[:12]
        ri=sorted([v for v in vertical if v[0]>=px],key=lambda v:v[0]-px)[:12]
        for l in le:
            for r in ri:
                a,b=l[0],max(l[1],r[1]);cw,ch=r[0]-a,min(l[2],r[2])-b
                if cw<max(20,width*.025) or ch<max(25,height*.035) or cw*ch>width*height*.55:continue
                tolerance=max(5,ch*.02)
                tops=[p for p,u,v in horizontal if b-tolerance<=p<=py and u<=a+5 and v>=a+cw-5]
                bottoms=[p for p,u,v in horizontal if py<=p<=b+ch+tolerance and u<=a+5 and v>=a+cw-5]
                if tops and bottoms:
                    y0,y1=max(tops),min(bottoms)
                    if y1-y0>=max(25,height*.035):rectangles.append(tuple(round(v) for v in (a,y0,cw,y1-y0)))
        if rectangles:rectangles=[min(rectangles,key=lambda r:r[2]*r[3])]
    if not rectangles:
        # Seed from a nearby closed door when a handle/leader opens the clicked door.
        # The final cabinet bounds below must still contain the actual click.
        nearby=[]
        for a,b,c,d in cores:
            dx=max(a-px,0,px-a-c);dy=max(b-py,0,py-b-d)
            if dx<=c and dy<=max(5,height*.01) or dy<=d and dx<=max(5,width*.01):
                nearby.append((dx*dx+dy*dy,(a,b,c,d)))
        if nearby:rectangles=[min(nearby,key=lambda item:item[0])[1]]
    if not rectangles:
        print("ODOO_DIMENSION_RESULT="+json.dumps({"error":"此处未找到明确的视图轮廓，请点击柜体内部；也可手工填写尺寸。"},ensure_ascii=False))
        sys.exit(0)
    smallest = min(r[2]*r[3] for r in rectangles)
    rectangles = sorted([r for r in rectangles if r[2]*r[3] <= smallest*4],key=lambda r:r[2]*r[3],reverse=True)[:4]
    x,y,w,h = rectangles[0]
    # Join adjacent door interiors belonging to the same view, never distant views.
    for _ in range(8):
        before=(x,y,w,h)
        for a,b,c,d in cores:
            aligned=abs(b-y)<max(5,h*.035) and abs(b+d-y-h)<max(5,h*.035)
            adjacent=a<=x+w+max(6,w*.06) and a+c>=x-max(6,w*.06)
            if aligned and adjacent:
                nx,ny=min(x,a),min(y,b)
                w,h=max(x+w,a+c)-nx,max(y+h,b+d)-ny
                x,y=nx,ny
        if before==(x,y,w,h):break
    # A handle cut-out can open one door's contour. Match the continuous paired
    # cabinet edges beside the clicked interior to include both doors in that case.
    for horizontal in (True,):
        span=w if horizontal else h
        mask=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(15,round(span*.6))) if horizontal else (max(15,round(span*.6)),1),np.uint8))
        edges=[]
        for c in cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            a,b,cw,ch=cv2.boundingRect(c)
            pos,start,end=(b+ch/2,a,a+cw) if horizontal else (a+cw/2,b,b+ch)
            origin=x if horizontal else y
            if start<=origin+span*.1 and end>=origin+span*.9:edges.append((pos,start,end))
        low,high=(y,y+h) if horizontal else (x,x+w)
        tolerance=max(5,(h if horizontal else w)*.035)
        first=sorted([e for e in edges if abs(e[0]-low)<=tolerance],key=lambda e:abs(e[0]-low))
        last=sorted([e for e in edges if abs(e[0]-high)<=tolerance],key=lambda e:abs(e[0]-high))
        if first and last:
            begin=max(first[0][1],last[0][1]);end=min(first[0][2],last[0][2])
            if span<=end-begin<=span*4:
                if horizontal:x,w=round(begin),round(end-begin)
                else:y,h=round(begin),round(end-begin)
    # Snap the joined interiors to nearby cabinet edges, excluding the more distant
    # dimension-line rectangle which used to enlarge the entire selected view.
    def nearby_edges(horizontal):
        length=max(15,round((w if horizontal else h)*.65))
        mask=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,length) if horizontal else (length,1),np.uint8))
        found=[]
        for c in cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
            a,b,cw,ch=cv2.boundingRect(c)
            if horizontal and cw>=w*.65 and a<=x+w*.15 and a+cw>=x+w*.85:found.append(b+ch/2)
            elif not horizontal and ch>=h*.65 and b<=y+h*.15 and b+ch>=y+h*.85:found.append(a+cw/2)
        return found
    horizontal_edges,vertical_edges=nearby_edges(True),nearby_edges(False)
    oldx,oldy,oldright,oldbottom=x,y,x+w,y+h
    frame_band=max(8,min(w,h)*.07)
    xs=[v for v in vertical_edges if oldx-frame_band<=v<=oldx+2]
    xe=[v for v in vertical_edges if oldright-2<=v<=oldright+frame_band]
    ys=[v for v in horizontal_edges if oldy-frame_band<=v<=oldy+2]
    ye=[v for v in horizontal_edges if oldbottom-2<=v<=oldbottom+frame_band]
    x=round(min(xs,default=oldx));y=round(min(ys,default=oldy))
    w=round(max(xe,default=oldright))-x;h=round(max(ye,default=oldbottom))-y
    body=(x,y,w,h)
    if not (x-3<=px<=x+w+3 and y-3<=py<=y+h+3):
        print("ODOO_DIMENSION_RESULT="+json.dumps({"error":"此处未找到明确的视图轮廓，请点击柜体内部；也可手工填写尺寸。"},ensure_ascii=False))
        sys.exit(0)

def distance_to_rect(cx,cy,r):
    a,b,c,d=r
    return max(a-cx,0,cx-a-c)**2+max(b-cy,0,cy-b-d)**2
neighbours=[r for r in cores if r[0]+r[2]<x-5 or r[0]>x+w+5 or r[1]+r[3]<y-5 or r[1]>y+h+5]
# The surrounding band includes dimension text, not the drawing's title block.
if not manual_rect:
    left=max(0,round(x-w*.65)); right=min(width,round(x+w*1.65))
    top=max(0,round(y-h*.25)); bottom=min(height,round(y+h*1.28))
tokens=[]
def token(text, points, confidence, origin):
    clean=re.sub(r"\s+", "",str(text)).replace("，", ".").strip()
    match=re.fullmatch(r"(?:(总宽|宽度|宽|总深|深度|深|总高|高度|高|[WDHwdh])[:：=]?)?(\d+(?:\.\d{1,3})?)(?:[mM]{2}|毫米)?",clean)
    if not match:
        return
    value=float(match.group(2))
    if not 0 < value <= 100000 or confidence < .75:
        return
    points=np.asarray(points,dtype=float)
    a,b=points.min(axis=0);c,d=points.max(axis=0)
    cx,cy=(a+c)/2,(b+d)/2
    if not(left<=cx<=right and top<=cy<=bottom) or (manual_rect and not (a>=left and b>=top and c<=right and d<=bottom)):
        return
    own_distance=distance_to_rect(cx,cy,body)
    if not manual_rect and own_distance and any(distance_to_rect(cx,cy,r)<own_distance*.45 for r in neighbours):
        return
    prefix=match.group(1) or ""
    axis="vertical" if prefix in ("总高","高度","高","H","h") else "horizontal" if prefix else ""
    if axis=="" and (cx < x+w*.12 or cx > x+w*.88) and y <= cy <= y+h:
        axis="vertical"
    if axis=="" and x-w*.15<=cx<=x+w*1.15 and (cy<y+h*.12 or cy>y+h*.88):
        axis="horizontal"
    if not axis:
        return
    if any(item["value"]==value and item["axis"]==axis and abs(item["cx"]-cx)<15 and abs(item["cy"]-cy)<15 for item in tokens):
        return
    tokens.append({"text":str(text).strip(),"value":value,"axis":axis,"cx":cx,"cy":cy,
        "rect":[float(a/width),float(b/height),float((c-a)/width),float((d-b)/height)],
        "confidence":round(float(confidence),3),"origin":origin,"explicit":bool(prefix)})

if pdf_page is not None:
    box=pdf_page.cropbox; cw,ch=float(box.width),float(box.height)
    turn=(int(pdf_page.get("/Rotate",0))+orientation)%360
    def pdf_point(a,b):
        u,v=(a-float(box.left))/cw,1-(b-float(box.bottom))/ch
        if turn==90:u,v=1-v,u
        elif turn==180:u,v=1-u,1-v
        elif turn==270:u,v=v,1-u
        return u*width,v*height
    def visitor(text, cm, tm, font, size):
        for match in re.finditer(r"\S+",text):
            part=match.group(0); offset=match.start()*size*.52; length=len(part)*size*.52
            def transform(a,b):
                q=a*tm[0]+b*tm[2]+tm[4];r=a*tm[1]+b*tm[3]+tm[5]
                return pdf_point(q*cm[0]+r*cm[2]+cm[4],q*cm[1]+r*cm[3]+cm[5])
            token(part,[transform(offset,-size*.2),transform(offset+length,-size*.2),
                        transform(offset+length,size*.85),transform(offset,size*.85)],1,"pdf_text")
    try: pdf_page.extract_text(visitor_text=visitor)
    except Exception: pass

# Raster/scanned drawings need local character reading only; no cabinet AI or remote service.
if not all(any(t["axis"]==axis for t in tokens) for axis in ("horizontal","vertical")):
    engine,problem=core["_rapidocr_reading_contract"]["_load_rapidocr_engine"]()
    if engine is not None:
        roi=image[top:bottom,left:right]
        for angle in (0,90):
            if angle and any(t["axis"]=="vertical" for t in tokens):break
            raster=roi if not angle else cv2.rotate(roi,cv2.ROTATE_90_CLOCKWISE)
            out=engine(raster,use_cls=True)
            if out.boxes is None:continue
            for coords,text,confidence in zip(out.boxes,out.txts,out.scores):
                pts=np.array(coords,dtype=float)
                if angle:
                    pts=np.column_stack([pts[:,1],roi.shape[0]-pts[:,0]])
                pts+=np.array([left,top]);token(text,pts,confidence,"local_ocr")

def line_groups(horizontal):
    length=max(8,round((w if horizontal else h)*.05))
    mask=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,length) if horizontal else (length,1),np.uint8))
    raw=[]
    for c in cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[0]:
        a,b,cw,ch=cv2.boundingRect(c)
        if horizontal and cw>=length:raw.append((b+ch/2,a,a+cw))
        elif not horizontal and ch>=length:raw.append((a+cw/2,b,b+ch))
    groups=[]
    for pos,start,end in sorted(raw):
        def can_join(group):
            if abs(group[0]-pos)>=4:return False
            gap=max(0,start-group[2],group[1]-end)
            span=w if horizontal else h
            if gap<=max(5,span*.08):return True
            if gap>span*.3:return False
            lo,hi=(group[2],start) if start>group[2] else (end,group[1])
            return any(t["axis"]==("horizontal" if horizontal else "vertical")
                and abs((t["cy"] if horizontal else t["cx"])-pos)<max(12,(t["rect"][3]*height if horizontal else t["rect"][2]*width)*1.5)
                and lo-5<=(t["cx"] if horizontal else t["cy"])<=hi+5 for t in tokens)
        found=next((g for g in groups if can_join(g)),None)
        if found:found[1]=min(found[1],start);found[2]=max(found[2],end)
        else:groups.append([pos,start,end])
    return groups
hlines,vlines=line_groups(True),line_groups(False)
def crosses(groups, coordinate, start, end, tolerance):
    return any(abs(p-coordinate)<=tolerance and a<=min(start,end)+tolerance and b>=max(start,end)-tolerance for p,a,b in groups)
for item in tokens:
    horizontal=item["axis"]=="horizontal";cx,cy=item["cx"],item["cy"]
    lines=hlines if horizontal else vlines
    spans=[]
    for pos,start,end in lines:
        if horizontal:
            if not (y-h*.3<=pos<=y+h*1.3) or y+5<pos<y+h-5:continue
            if abs(pos-cy)>max(35,h*.1):continue
            if not start-w*.05<=cx<=end+w*.05:continue
            error=(abs(start-x)+abs(end-x-w))/w
            edge=y if pos<y+h/2 else y+h
            linked=error<.2 and crosses(vlines,start,edge,pos,max(8,w*.04)) and crosses(vlines,end,edge,pos,max(8,w*.04))
        else:
            if not (x-w*.5<=pos<=x+w*1.5) or x+5<pos<x+w-5:continue
            if abs(pos-cx)>max(35,w*.2):continue
            if not start-h*.05<=cy<=end+h*.05:continue
            error=(abs(start-y)+abs(end-y-h))/h
            edge=x if pos<x+w/2 else x+w
            linked=error<.2 and crosses(hlines,start,edge,pos,max(8,h*.04)) and crosses(hlines,end,edge,pos,max(8,h*.04))
        distance=abs(pos-(cy if horizontal else cx))
        spans.append((distance,error,linked))
    nearest=min(spans,key=lambda pair:pair[0]) if spans else None
    item["linked"]=bool(nearest and nearest[2])
    item["score"]=round((8 if item["explicit"] else 0)+(6 if item["linked"] else 0)+(5-12*nearest[1] if nearest else 0),3)
    item["explicit_label"]=item["explicit"]
    item.pop("cx");item.pop("cy");item.pop("explicit")
for axis in ("horizontal","vertical"):
    if any(t["axis"]==axis and t["linked"] for t in tokens):
        tokens=[t for t in tokens if t["axis"]!=axis or t["linked"] or t["explicit_label"]]
tokens=sorted(tokens,key=lambda t:(t["axis"],-t["score"],-t["confidence"]))[:50]
for index,item in enumerate(tokens):item["id"]=str(index+1)
def best(axis):
    group=[t for t in tokens if t["axis"]==axis]
    if not group:return None
    head=group[0];others=[t for t in group if t["value"]!=head["value"]]
    if not head["linked"] and not head["explicit_label"]:return None
    if others and head["score"]-others[0]["score"]<.7:return None
    return head["id"]
def display_rect(r):
    x,y,w,h=r
    if rotation==90:x,y,w,h=1-y-h,x,h,w
    elif rotation==180:x,y=1-x-w,1-y-h
    elif rotation==270:x,y,w,h=y,1-x-w,h,w
    return [round(v,6) for v in (x,y,w,h)]
def norm(r):return display_rect([r[0]/width,r[1]/height,r[2]/width,r[3]/height])
for item in tokens:item["rect"]=display_rect(item["rect"])
body_rect=norm(body)
rx,ry,rw,rh=body_rect
extent=[rx,ry,rx+rw,ry+rh]
for item in tokens:
    a,b,c,d=item["rect"]
    extent=[min(extent[0],a),min(extent[1],b),max(extent[2],a+c),max(extent[3],b+d)]
regions=[[max(0,extent[0]-.004),max(0,extent[1]-.004),min(1,extent[2]+.004)-max(0,extent[0]-.004),min(1,extent[3]+.004)-max(0,extent[1]-.004)],body_rect]
if manual_rect:regions=[display_rect(manual_rect)]
output={"selection_mode":"manual" if manual_rect else "auto","reader_version":3,"page":page_number,"rotation":display_rotation,"orientation":orientation,"regions":regions,"body":body_rect,
    "tokens":tokens,"horizontal":best("horizontal"),"vertical":best("vertical"),"point":click_point}
print("ODOO_DIMENSION_RESULT="+json.dumps(output,ensure_ascii=False),flush=True)
