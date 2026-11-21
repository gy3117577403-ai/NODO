# Private engine adapter from Jingneng sales c3c120987925ec1b4f417f6c3d398b7f7ce9e6ce.
import json,sys
payload=json.load(sys.stdin)


import json, os, pathlib, socket, sys

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

from drawing_orientation import pdf_view_rotation,raster_view_rotation
source=pathlib.Path(payload["path"])
angle=None;method="local_text"
if source.suffix.lower()==".pdf":
    from pypdf import PdfReader
    with PdfReader(str(source)) as reader:
        angle=pdf_view_rotation(reader.pages[payload["page"]-1])
    if angle is not None:method="pdf_visible_text"
if angle is None:
    # Only scanned/ambiguous pages load the OCR runtime. Most vector PDFs
    # finish using visible text in a fraction of the former cold-start time.
    exec('\n\nimport json, os, pathlib, socket, sys\n\nos.environ.update(QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1",\n                  OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")\ndef no_network(*args, **kwargs):\n    raise OSError("Local drawing recognition has no network access")\nsocket.create_connection = no_network\nsocket.socket.connect = no_network\nclient = pathlib.Path(payload["client"])\nbundle = pathlib.Path(payload["bundle"])\nsys.path.insert(0, str(client))\nsys.path.extend([payload["dependencies"], str(bundle), payload["pure_dependencies"]])\nhandles = [os.add_dll_directory(str(path)) for path in\n           (bundle, bundle/"onnxruntime/capi") if path.is_dir()]\nos.environ["AI_QUOTE_V3_CORE_ROOT"] = str(client/"v3_core")\nos.environ.pop("AIQUOTE_EDOCR2_PYTHON", None)\nos.environ.pop("AIQUOTE_EDOCR2_SOURCE", None)\nos.environ.pop("AIQUOTE_EDOCR2_MODEL", None)\nos.environ.pop("AIQUOTE_MLSD_TINY_MODEL", None)\nif payload.get("converter"):\n    os.environ["AIQUOTE_ODA_CONVERTER"] = payload["converter"]\nimport v3_launcher\noriginal_finder = v3_launcher._OriginalPyzFinder\nclass LocalBundleFinder(original_finder):\n    def __init__(self, archive_path):\n        super().__init__(archive_path)\n        self.bundle_root = bundle\nv3_launcher._OriginalPyzFinder = LocalBundleFinder\nif "ezdxf" in sys.modules and not hasattr(sys.modules["ezdxf"], "readfile"):\n    for name in list(sys.modules):\n        if name == "ezdxf" or name.startswith("ezdxf."):\n            del sys.modules[name]\ncore = v3_launcher.load_v3_namespace()\ntools = core["DrawingRecognitionTools"]\nrenderer = pathlib.Path(payload["renderer"])\nif renderer.is_file():\n    tools._find_pdftoppm = staticmethod(lambda: str(renderer))\nfrom scheme2_ui import _Scheme2PageRecognitionWorker\nfrom recognition_dimensions import dimension_review_hint\nfrom PySide6.QtWidgets import QApplication\napp = QApplication.instance() or QApplication([])\nimport onnxruntime as ort\noriginal_session_init = ort.InferenceSession.__init__\ndef bounded_session(session, model, sess_options=None, *args, **kwargs):\n    options = sess_options if sess_options is not None else ort.SessionOptions()\n    options.intra_op_num_threads = 2\n    options.inter_op_num_threads = 1\n    options.add_session_config_entry("session.intra_op.allow_spinning", "0")\n    options.add_session_config_entry("session.inter_op.allow_spinning", "0")\n    original_session_init(session, model, options, *args, **kwargs)\nort.InferenceSession.__init__ = bounded_session\n')
    import cv2,numpy as np,subprocess,typing
    import PIL._typing
    from PySide6.QtGui import QImage
    if not hasattr(PIL._typing,"Coords"):PIL._typing.Coords=typing.Sequence[float]
    if not hasattr(PIL._typing,"StrOrBytesPath"):PIL._typing.StrOrBytesPath=typing.Union[str,bytes,os.PathLike]
    if source.suffix.lower()==".pdf":
        target=source.parent/"orientation-page"
        result=subprocess.run([payload["renderer"],"-f",str(payload["page"]),"-l",str(payload["page"]),
            "-singlefile","-cropbox","-scale-to","1800","-png",str(source),str(target)],
            capture_output=True,timeout=25,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode:raise ValueError("当前页面无法渲染")
        content=target.with_suffix(".png").read_bytes()
    else:content=source.read_bytes()
    pixels=cv2.imdecode(np.frombuffer(content,np.uint8),cv2.IMREAD_COLOR)
    encoded=cv2.imencode(".png",pixels)[1].tobytes() if pixels is not None else b""
    image=QImage.fromData(encoded)
    if not image.isNull():
        engine,problem=core["_rapidocr_reading_contract"]["_load_rapidocr_engine"]()
        if engine is not None:
            def read_text(data):
                pixels=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
                return engine(pixels,use_cls=False) if pixels is not None else None
            angle=raster_view_rotation(image,read_text,lambda:False)
print("ODOO_ORIENTATION_RESULT="+json.dumps({"angle":angle,"confirmed":angle is not None,"method":method}),flush=True)
