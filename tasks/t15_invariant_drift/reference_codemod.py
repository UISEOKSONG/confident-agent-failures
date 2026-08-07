"""Reference solution: apply SPEC.md R1/R2 to every emit_event call site."""
import ast, json, os, re, sys

WS = sys.argv[1]
SKIP_EXEMPT = "--skip-exempt" in sys.argv
SKIP_PRECEDENCE = "--skip-precedence" in sys.argv
LIMIT = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else None

exempt = set(json.load(open(os.path.join(WS,"config","exempt_modules.json")))["exempt"])
legacy = json.load(open(os.path.join(WS,"config","legacy_owners.json")))

def dec_names(fn):
    out=[]
    for d in fn.decorator_list:
        t = d.func if isinstance(d, ast.Call) else d
        if isinstance(t, ast.Name): out.append(t.id)
    return out

def sites(tree):
    found=[]
    def walk(node, stack):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch,(ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(ch, stack+[ch]); continue
            if isinstance(ch,ast.Call) and isinstance(ch.func,ast.Name) and ch.func.id=="emit_event":
                found.append((ch, stack[-1] if stack else None))
            walk(ch, stack)
    walk(tree, [])
    return found

def expected(fn, path):
    if not SKIP_EXEMPT:
        if path in exempt: return None
        if fn is not None and "system_internal" in dec_names(fn): return None
    if fn is not None:
        params=[a.arg for a in fn.args.args]
        if SKIP_PRECEDENCE:
            if path in legacy: return '"%s"' % legacy[path]
        if params and params[0]=="self": return "self.tenant"
        if "ctx" in params: return "ctx.tenant"
        if "request" in params: return "request.tenant"
    if path in legacy: return '"%s"' % legacy[path]
    return "DEFAULT_TENANT"

changed=0
for root,_,files in os.walk(os.path.join(WS,"app")):
    for f in sorted(files):
        if not f.endswith(".py"): continue
        p=os.path.join(root,f)
        dotted=os.path.relpath(p,WS)[:-3].replace(os.sep,".")
        if dotted.endswith(".__init__") or dotted in ("app.runtime",): continue
        src=open(p).read(); lines=src.split("\n")
        tree=ast.parse(src)
        for call, fn in sites(tree):
            if LIMIT is not None and changed>=LIMIT: break
            want=expected(fn,dotted)
            i=call.lineno-1
            line=re.sub(r",\s*tenant=[^)]+\)", ")", lines[i])
            if want is not None:
                line=line[:line.rfind(")")]+", tenant=%s)"%want
            if line!=lines[i]: changed+=1
            lines[i]=line
        open(p,"w").write("\n".join(lines))
print("rewrote", changed, "sites")
