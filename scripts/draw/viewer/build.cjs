// Offline rebuild from the original 0.57.3 source and the pinned local packages.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {execFileSync} = require("node:child_process");
const {createRequire} = require("node:module");
const extendViewer = require("./viewer_extension.cjs");
const [, , checkout, packages] = process.argv;
if (!checkout || !packages) throw Error("用法：node build.cjs 京能源码仓库 含node_modules的依赖目录");
const revision = "cf8681fcf38e282f2fb2b8aa0c6a96ba5d96af24";
const root = path.resolve(__dirname, "../../..");
const output = path.join(root, "addons/nodo_draw/static/lib/ae");
const deps = path.resolve(packages);
const local = createRequire(path.join(deps, "package.json"));
const versions = {three:"0.186.1", "three-mesh-bvh":"0.9.16", react:"19.3.1",
    "react-dom":"19.3.1", scheduler:"0.28.0", esbuild:"0.28.2"};
const licenses = [];
for (const [name, version] of Object.entries(versions)) {
    const dir = path.join(deps, "node_modules", name);
    const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json")));
    if (pkg.version !== version || pkg.license !== "MIT") throw Error("依赖版本或许可不符 " + name);
    if (name !== "esbuild") licenses.push(name + " " + version + "\n" + fs.readFileSync(path.join(dir, "LICENSE"), "utf8").trim());
}

function git(args) {
    return execFileSync("git", ["-C", path.resolve(checkout), ...args], {
        env: {...process.env, GIT_NO_LAZY_FETCH: "1"}, stdio: ["ignore", "pipe", "pipe"],
    });
}
const paths = new Set(git(["ls-tree", "-r", "--name-only", revision, "src/ae-cabinet",
    "engineering/ae-cabinet/materials.json", "engineering/ae-cabinet/sheet-rules.json"])
    .toString().trim().split(/\r?\n/));
function readSource(file) {
    if (!file.startsWith("engineering/")) return git(["show", revision + ":" + file]);
    // The installed CAD payload has these files even when the Git clone is partial.
    const data = fs.readFileSync(path.join(root, ".nodo-draw", file), "utf8").replace(/\r\n/g, "\n");
    const oid = crypto.createHash("sha1").update("blob " + Buffer.byteLength(data) + "\0").update(data).digest("hex");
    if (oid !== git(["rev-parse", revision + ":" + file]).toString().trim()) throw Error("工程依据版本不符 " + file);
    return data;
}
const sources = {name: "jingneng-release", setup(build) {
    build.onResolve({filter: /^@nodo\/drill-pick$/}, () => ({path: path.join(__dirname, "drill_pick.js")}));
    build.onResolve({filter: /^@jingneng\/(Viewer|coordinates|holePlacement|holeShape|HoleGizmo)$/}, ({path: name}) => {
        const file = name.slice("@jingneng/".length);
        return {path: "src/ae-cabinet/" + file + (file === "Viewer" ? ".tsx" : ".ts"), namespace: "ae"};
    });
    build.onResolve({filter: /^\./, namespace: "ae"}, args => {
        const base = path.posix.join(path.posix.dirname(args.importer), args.path);
        const file = [base, base + ".ts", base + ".tsx"].find(key => paths.has(key));
        if (!file) throw Error("原版视口缺少引用 " + base);
        return {path: file, namespace: "ae"};
    });
    build.onLoad({filter: /.*/, namespace: "ae"}, ({path: file}) => {
        const source = readSource(file);
        return {contents: file === "src/ae-cabinet/Viewer.tsx" ? extendViewer(source) : source,
            loader: path.extname(file).slice(1), resolveDir: deps};
    });
}};
async function main() {
    const build = await local("esbuild").build({
        entryPoints: [path.join(__dirname, "entry.jsx")], plugins: [sources],
        nodePaths: [path.join(deps, "node_modules")], bundle: true, minify: true, write: false,
        platform: "browser", target: "es2022", format: "iife", globalName: "nodoDrawAE0573",
        jsx: "automatic", legalComments: "inline", define: {"import.meta.env.DEV": "false",
            "import.meta.env.VITE_AE_DIAGNOSTICS": '"0"', "process.env.NODE_ENV": '"production"'},
    });
    fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, "viewport.min.js"), build.outputFiles[0].contents);
    fs.writeFileSync(path.join(output, "LICENSES.txt"), licenses.join("\n\n") + "\n");
    console.log("原版 AE 视口已构建", revision, build.outputFiles[0].contents.length, "bytes");
}
main().catch(error => {console.error(error); process.exitCode = 1;});
