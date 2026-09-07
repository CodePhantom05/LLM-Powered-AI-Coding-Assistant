import json
import re

ENTRY_CANDIDATES = [
    "src/main.tsx", "src/main.ts", "src/main.jsx", "src/main.js",
    "src/index.tsx", "src/index.ts", "src/index.jsx", "src/index.js",
    "main.tsx", "main.jsx", "main.ts", "main.js",
    "index.tsx", "index.jsx",
]

CODE_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js")
ENTRY_BASENAMES = ("main.tsx", "main.jsx", "main.ts", "main.js",
                    "index.tsx", "index.jsx", "index.ts", "index.js")
APP_BASENAMES = ("app.tsx", "app.jsx", "app.ts", "app.js")


def is_probably_react_project(files: dict) -> bool:
    """True if the generated project looks like a React/TS component-based
    app (as opposed to a plain static HTML/CSS/JS site)."""
    if any(name.lower().endswith((".tsx", ".jsx")) for name in files):
        return True
    pkg = files.get("package.json")
    if pkg and '"react"' in pkg:
        return True
    return False


def _entry_from_index_html(files: dict) -> str | None:
    """Vite-style projects declare their real entry in index.html via
    <script type="module" src="/src/main.tsx">. Parsing that is the most
    reliable way to find the entry when it doesn't match a conventional path."""
    html = files.get("index.html")
    if not html:
        return None
    for match in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        src = match.group(1).lstrip("/")
        if src in files and files[src]:
            return src
        # try common prefix variations (some generators omit/add "./")
        for prefix_stripped in (src, src.lstrip("./")):
            if prefix_stripped in files and files[prefix_stripped]:
                return prefix_stripped
    return None


def _entry_by_basename_search(files: dict) -> str | None:
    """Search every file (any directory depth) for a conventional entry
    filename, preferring shallower paths and .tsx/.jsx over .ts/.js."""
    candidates = []
    for name, content in files.items():
        if not content:
            continue
        basename = name.rsplit("/", 1)[-1].lower()
        if basename in ENTRY_BASENAMES:
            depth = name.count("/")
            ext_rank = 0 if basename.endswith((".tsx", ".jsx")) else 1
            name_rank = 0 if basename.startswith("main") else 1
            candidates.append((depth, name_rank, ext_rank, name))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


def _synthesize_entry_from_app(files: dict) -> tuple[str, str] | None:
    """Last resort: if there's an App-like component but no dedicated entry
    file at all, synthesize a minimal main module that renders it directly.
    Returns (virtual_entry_key, synthetic_source) or None."""
    candidates = []
    for name, content in files.items():
        if not content:
            continue
        basename = name.rsplit("/", 1)[-1].lower()
        if basename in APP_BASENAMES:
            depth = name.count("/")
            candidates.append((depth, name))
    if not candidates:
        return None
    candidates.sort()
    app_path = candidates[0][1]
    import_path = "./" + app_path.rsplit(".", 1)[0]
    synthetic = (
        "import React from 'react';\n"
        "import { createRoot } from 'react-dom/client';\n"
        f"import App from '{import_path}';\n"
        "const rootEl = document.getElementById('root');\n"
        "if (rootEl) { createRoot(rootEl).render(React.createElement(App)); }\n"
    )
    return "__virtual_main__.tsx", synthetic


def find_entry_point(files: dict) -> tuple[str, str | None] | None:
    """Returns (entry_key, synthetic_source_or_None). synthetic_source is set
    only for the virtual-entry fallback, where entry_key doesn't correspond
    to a real file in `files`."""
    for candidate in ENTRY_CANDIDATES:
        if candidate in files and files[candidate]:
            return candidate, None

    from_html = _entry_from_index_html(files)
    if from_html:
        return from_html, None

    from_basename = _entry_by_basename_search(files)
    if from_basename:
        return from_basename, None

    synthesized = _synthesize_entry_from_app(files)
    if synthesized:
        return synthesized

    return None


def build_react_preview_html(files: dict) -> str | None:
    """Returns a full HTML document string for the live preview iframe, or
    None if no usable entry point was found (caller should show a fallback
    message in that case)."""
    found = find_entry_point(files)
    if found is None:
        return None
    entry, synthetic_source = found

    js_modules = {
        name: content
        for name, content in files.items()
        if content is not None and name.lower().endswith(CODE_EXTENSIONS)
    }
    if synthetic_source is not None:
        js_modules[entry] = synthetic_source
    css_modules = {
        name: content
        for name, content in files.items()
        if content is not None and name.lower().endswith(".css")
    }

    modules_json = json.dumps(js_modules)
    css_json = json.dumps(css_modules)
    entry_json = json.dumps(entry)

    # NOTE: plain string, not an f-string — the JS/CSS below is full of `{}`
    # braces that would otherwise need constant escaping.
    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>html,body,#root{height:100%;margin:0;} body{font-family:system-ui,sans-serif;}
#__preview_error{display:none;padding:16px;color:#b91c1c;background:#fef2f2;font-family:monospace;white-space:pre-wrap;border-bottom:2px solid #b91c1c;}</style>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
<script src="https://unpkg.com/@babel/standalone@7/babel.min.js" crossorigin></script>
</head>
<body>
<div id="__preview_error"></div>
<div id="root"></div>
<script>
(function () {
  var rawModules = __MODULES_JSON__;
  var cssModules = __CSS_JSON__;
  var entryPath = __ENTRY_JSON__;

  function showError(err) {
    var box = document.getElementById('__preview_error');
    box.style.display = 'block';
    box.textContent = 'Preview error: ' + (err && err.message ? err.message : String(err));
    console.error(err);
  }

  function normalize(path) {
    var parts = path.split('/');
    var stack = [];
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      if (part === '.' || part === '') continue;
      if (part === '..') stack.pop();
      else stack.push(part);
    }
    return stack.join('/');
  }

  function resolveRelative(fromPath, importPath) {
    var fromDir = fromPath.indexOf('/') >= 0 ? fromPath.slice(0, fromPath.lastIndexOf('/')) : '';
    var combined = fromDir ? fromDir + '/' + importPath : importPath;
    return normalize(combined);
  }

  function findJsModule(resolved) {
    var candidates = [
      resolved, resolved + '.tsx', resolved + '.ts', resolved + '.jsx', resolved + '.js',
      resolved + '/index.tsx', resolved + '/index.ts', resolved + '/index.jsx', resolved + '/index.js'
    ];
    for (var i = 0; i < candidates.length; i++) {
      if (rawModules[candidates[i]] !== undefined) return candidates[i];
    }
    return null;
  }

  function findCssModule(resolved) {
    var candidates = [resolved, resolved + '.css'];
    for (var i = 0; i < candidates.length; i++) {
      if (cssModules[candidates[i]] !== undefined) return candidates[i];
    }
    return null;
  }

  var LucideFallback = new Proxy({}, {
    get: function () {
      return function (props) {
        return React.createElement('span', props || {}, '');
      };
    }
  });

  var externals = {
    'react': function () { return React; },
    'react-dom': function () { return ReactDOM; },
    'react-dom/client': function () { return ReactDOM; },
    'lucide-react': function () { return LucideFallback; }
  };

  var compiledCache = {};
  var execCache = {};
  var cssInjected = {};

  function compile(path, source) {
    if (compiledCache[path]) return compiledCache[path];
    var out = Babel.transform(source, {
      filename: path,
      presets: ['react', 'typescript'],
      plugins: ['transform-modules-commonjs'],
      sourceType: 'module'
    }).code;
    compiledCache[path] = out;
    return out;
  }

  function requireModule(fromPath, importPath) {
    if (importPath.charAt(0) !== '.') {
      if (externals[importPath]) return externals[importPath]();
      console.warn('Unresolved external import "' + importPath + '" (from ' + fromPath + ') — using empty stub.');
      return {};
    }

    var resolved = resolveRelative(fromPath, importPath);

    var cssKey = findCssModule(resolved);
    if (cssKey) {
      if (!cssInjected[cssKey]) {
        var style = document.createElement('style');
        style.textContent = cssModules[cssKey];
        document.head.appendChild(style);
        cssInjected[cssKey] = true;
      }
      return {};
    }

    var jsKey = findJsModule(resolved);
    if (!jsKey) {
      console.warn('Module not found: "' + resolved + '" (imported from ' + fromPath + ')');
      return {};
    }
    if (execCache[jsKey]) return execCache[jsKey].exports;

    var mod = { exports: {} };
    execCache[jsKey] = mod;
    var compiledCode = compile(jsKey, rawModules[jsKey]);
    var localRequire = function (p) { return requireModule(jsKey, p); };
    var fn = new Function('exports', 'require', 'module', 'React', compiledCode);
    fn(mod.exports, localRequire, mod, React);
    return mod.exports;
  }

  try {
    requireModule('', './' + entryPath);
  } catch (err) {
    showError(err);
  }
})();
</script>
</body>
</html>"""

    html = html.replace("__MODULES_JSON__", modules_json)
    html = html.replace("__CSS_JSON__", css_json)
    html = html.replace("__ENTRY_JSON__", entry_json)
    return html