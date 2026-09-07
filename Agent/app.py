import io
import os
import zipfile

import streamlit as st

from graph import run_agent
from tools import collect_generated_files
from preview import is_probably_react_project, build_react_preview_html

st.set_page_config(page_title="Coder Agent", layout="wide")
st.title("🛠️ Coder Agent")
st.caption("Describe an app. The agent plans, architects, and codes it — preview and download below.")

with st.sidebar:
    st.subheader("Diagnostics")
    key_present = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    st.write("API key loaded:", "✅" if key_present else "❌ (check .env location / cwd)")
    st.caption(f"Working directory: {os.getcwd()}")

if "generated_files" not in st.session_state:
    st.session_state.generated_files = None
if "last_prompt" not in st.session_state:
    st.session_state.last_prompt = ""
if "skipped_files" not in st.session_state:
    st.session_state.skipped_files = []
if "daily_quota_exhausted" not in st.session_state:
    st.session_state.daily_quota_exhausted = False

user_prompt = st.text_area(
    "What do you want to build?",
    placeholder="e.g. Build a colourful modern todo app (or: 'as a React + Tailwind app')",
    height=100,
)

generate_clicked = st.button("Generate", type="primary", disabled=not user_prompt.strip())

if generate_clicked:
    with st.spinner("Planning, architecting, and coding your app... this can take a minute."):
        try:
            result = run_agent(user_prompt)
            st.session_state.generated_files = collect_generated_files()
            st.session_state.last_prompt = user_prompt
            st.session_state.skipped_files = result.get("skipped_files", [])
            st.session_state.daily_quota_exhausted = result.get("daily_quota_exhausted", False)
        except Exception as e:
            st.session_state.generated_files = None
            st.error(f"Generation failed: {e}")
            st.exception(e)  # shows the full traceback in the UI

files = st.session_state.generated_files

# Drop any entries with empty/invalid names (e.g. from a malformed tool call
# during generation) — these can otherwise crash st.tabs() with an empty label.
if files:
    files = {name: content for name, content in files.items() if name and name.strip()}

if st.session_state.daily_quota_exhausted:
    st.error(
        "⏳ Groq's daily free-tier token quota for the coder model is exhausted "
        "for today. Any files below were generated before quota ran out; the "
        "rest were skipped. Wait for Groq's daily reset (see the skipped-file "
        "errors below for the exact retry time), or upgrade to Groq's Dev Tier "
        "at https://console.groq.com/settings/billing."
    )

if files:
    try:
        st.success(f"Generated {len(files)} file(s) for: \"{st.session_state.last_prompt}\"")

        if st.session_state.skipped_files:
            with st.expander(f"⚠️ {len(st.session_state.skipped_files)} file(s) were skipped after repeated failures", expanded=False):
                for note in st.session_state.skipped_files:
                    st.write(note)

        # ---- Live preview ----
        st.subheader("Live Preview")
        if is_probably_react_project(files):
            react_html = build_react_preview_html(files)
            if react_html:
                st.caption(
                    "React/TypeScript preview — bundled live in your browser "
                    "(Babel + a lightweight module loader, no build step)."
                )
                st.components.v1.html(react_html, height=700, scrolling=True)
            else:
                code_files = [f for f in files if f.lower().endswith((".tsx", ".jsx", ".ts", ".js"))]
                st.info(
                    "This looks like a React/TS project, but no entry point could "
                    "be found — checked common paths (src/main.tsx etc.), "
                    "index.html's script tag, and any main/index/App file at any "
                    "depth. Detected code files: " + ", ".join(code_files[:15]) +
                    (f" (+{len(code_files) - 15} more)" if len(code_files) > 15 else "") +
                    ". See the code below."
                )
        else:
            html_files = [f for f in files if f.lower().endswith(".html")]
            if html_files:
                preview_target = st.selectbox("Preview file", html_files, index=0) if len(html_files) > 1 else html_files[0]

                html_content = files[preview_target] or ""

                # Inline any same-named/sibling .css and .js files that aren't already
                # linked absolutely, so the iframe preview is self-contained.
                css_snippets = "\n".join(
                    f"<style>{content}</style>"
                    for name, content in files.items()
                    if name.lower().endswith(".css") and content
                )
                js_snippets = "\n".join(
                    f"<script>{content}</script>"
                    for name, content in files.items()
                    if name.lower().endswith(".js") and content
                )

                if "</head>" in html_content and css_snippets:
                    html_content = html_content.replace("</head>", css_snippets + "\n</head>")
                else:
                    html_content = css_snippets + html_content

                if "</body>" in html_content and js_snippets:
                    html_content = html_content.replace("</body>", js_snippets + "\n</body>")
                else:
                    html_content = html_content + js_snippets

                st.components.v1.html(html_content, height=600, scrolling=True)
            else:
                st.info("No HTML file found in the generated output, so no live preview is available — see the code below.")

        # ---- Code viewer ----
        st.subheader("Generated Files")
        # Tab labels must be unique and non-empty; dedupe defensively just in case.
        tab_labels = []
        seen = set()
        for name in files:
            label = name
            suffix = 2
            while label in seen:
                label = f"{name} ({suffix})"
                suffix += 1
            seen.add(label)
            tab_labels.append(label)
        tabs = st.tabs(tab_labels)
        for tab, (name, content) in zip(tabs, files.items()):
            with tab:
                if content is None:
                    st.write("Binary file (not shown).")
                else:
                    lang = name.split(".")[-1] if "." in name else "text"
                    st.code(content, language=lang)

        # ---- Download instead of persistent storage ----
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                if content is not None:
                    zf.writestr(name, content)
        zip_buffer.seek(0)

        st.download_button(
            label="⬇️ Download project as ZIP",
            data=zip_buffer,
            file_name="generated_project.zip",
            mime="application/zip",
        )
    except Exception as e:
        st.error(f"Something went wrong while displaying the generated files: {e}")
        st.exception(e)
elif st.session_state.generated_files is not None:
    # run_agent() completed without raising, but produced zero usable files —
    # most likely every coder step hit a retry limit and was skipped.
    st.warning(
        "Generation finished, but no files were produced. Each coder step is "
        "retried up to 3 times before being skipped."
    )
    if st.session_state.skipped_files:
        st.subheader(f"Skipped {len(st.session_state.skipped_files)} file(s)")
        for note in st.session_state.skipped_files:
            st.code(note, language=None)
    else:
        st.caption(
            "No skipped-file details were recorded, which suggests the Planner "
            "or Architect step itself produced an empty task list — check your "
            "terminal for the Plan/TaskPlan output."
        )
else:
    st.info("Enter a prompt above and click Generate to get started.")