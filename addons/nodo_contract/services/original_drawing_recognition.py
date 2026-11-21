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
source = pathlib.Path(payload["path"])
page_sources = [(source, 0)]
if source.suffix.lower() == ".pdf":
    from pypdf import PdfReader
    with PdfReader(str(source)) as reader:
        page_sources = [(source, index) for index in range(len(reader.pages))]
elif source.suffix.lower() in (".tif", ".tiff"):
    from PIL import Image
    with Image.open(source) as image:
        page_sources = []
        for index in range(image.n_frames):
            image.seek(index)
            target = source.parent / ("frame-%s.png" % (index+1))
            image.convert("RGB").save(target)
            page_sources.append((target, 0))
pages, candidates, errors = [], [], []
for index, (page_source, source_index) in enumerate(page_sources):
    if index != payload.get("page_index", 0):
        continue
    entry = {"source_path":str(page_source), "page_index":source_index,
             "page_count":len(page_sources), "key":"page-%s" % (index+1)}
    results, failures = [], []
    task = _Scheme2PageRecognitionWorker(tools, entry)
    task.succeeded.connect(lambda _key, value: results.append(value))
    task.failed.connect(lambda _key, message: failures.append(message))
    task.run()
    if failures or not results:
        errors.append({"page":index+1, "message":failures[0] if failures else "未返回识别结果"})
        continue
    result = results[0]
    result["source_page_number"] = index+1
    pages.append(result)
    records = result.get("cabinet_candidates") or core["build_review_candidates"](result) or [result]
    for record in records:
        if not isinstance(record, dict):
            continue
        record["source_page_number"] = index+1
        record["manual_reviewed"] = False
        record["manual_confirmation_checked"] = False
        features = record.get("recognized_features") or {}
        facts = features.get("facts") or {}
        suggested = {}
        dimensions = record.get("dimensions") or []
        recognition = record.get("dimension_recognition") or {}
        if dimensions and recognition.get("status") == "recognized":
            width, height, depth = dimensions[0]
            suggested.update(width_mm=width, height_mm=height, depth_mm=depth)
        # Preserve a detected ganged width instead of flattening it to one total.
        specification = str(record.get("specification") or "")
        split = re.match(r"^\s*[（(]\s*(\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)+)\s*[)）]\s*[×xX*/]", specification)
        if split:
            parts = [float(part.strip()) for part in split.group(1).split("+")]
            if 2 <= len(parts) <= 20 and all(part > 0 for part in parts):
                suggested.update(width_expression="+".join(f"{part:g}" for part in parts), width_mm=sum(parts))
        for target, fact_name in (("material","material"), ("thickness_mm","body_thickness_mm")):
            fact = facts.get(fact_name) or {}
            if fact.get("value") is not None and fact.get("origin") == "drawing":
                if target != "material" or fact["value"] in ("SUS304", "SUS316", "SECC", "SGCC"):
                    suggested[target] = fact["value"]
        door = (facts.get("door_layout") or {}).get("value")
        if door:
            suggested["door_type"] = {"front_single":"前单开门", "front_double":"前双开门"}.get(door, str(door))
        code = record.get("product_code")
        if code:
            suggested["product_code"] = str(code)
        text = str(record.get("raw_text") or record.get("text") or "")
        attachments = list(core["MainWindow"].recommend_attachment_names(text) or [])
        notes = []
        if record.get("specification"):
            notes.append("规格候选：" + str(record["specification"]))
        material = facts.get("material") or {}
        if material.get("value"):
            notes.append("材质依据：" + str(material.get("evidence") or material["value"]))
        if record.get("height_terms_mm"):
            notes.append("高度含箱体与底座分项，请按原图核对：" + str(record["height_terms_mm"]))
        if recognition.get("status") != "recognized":
            notes.append(dimension_review_hint(record))
        if attachments:
            notes.append("附件建议（数量待核对）："+"、".join(attachments))
        warnings = record.get("specification_warnings") or []
        notes.extend(str(warning) for warning in warnings)
        summary = "\n".join(dict.fromkeys(note for note in notes if note))
        candidates.append({"name":record.get("name") or result.get("name") or "待复核项目",
                           "page":index+1, "suggested":suggested,
                           "summary":summary or "请对照原图核对选型参数。",
                           "attachment_names":attachments, "raw":record})
from hashlib import sha256
output = {"schema_version":1, "page_count":len(page_sources), "pages":pages,
          "candidates":candidates, "errors":errors,
          "core_manifest_sha256":sha256((client/"v3_core/manifest.json").read_bytes()).hexdigest()}
print("ODOO_RECOGNITION_RESULT="+json.dumps(output,ensure_ascii=False,default=str),flush=True)
