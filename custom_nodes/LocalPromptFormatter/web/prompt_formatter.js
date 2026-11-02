import { app } from "../../scripts/app.js";

const NODE_NAME = "LocalPromptFormatter";

const WIDGET_META = {
    required_text: { type: "text", section: "auth", label: "Required Text", desc: "Enter any non-blank text. Checked locally only." },
    base_quality: { type: "combo", section: "settings", label: "Base Quality", desc: "Pipeline quality scaling level." },
    master_strength: { type: "slider", section: "settings", label: "Master Strength", min: 0, max: 1, step: 0.01, desc: "Final enhancement blend factor." },
    real_skin_texture: { type: "toggle", section: "settings", label: "Skin Texture", desc: "Protect and enhance realistic skin details." },
    natural_lighting: { type: "toggle", section: "settings", label: "Natural Lighting", desc: "Dynamic cinematic lighting adjustments." }
};

function injectCSS() {
    if (document.getElementById("prompter-styles")) return;
    const style = document.createElement("style");
    style.id = "prompter-styles";
    style.textContent = `
.prompter-root {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0A0A0F;
    border-radius: 8px;
    color: #D0D0C0;
    user-select: none;
    width: 100%;
    min-width: 0;
    height: 100%;
    box-sizing: border-box;
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-width: thin;
    scrollbar-color: #333344 transparent;
}
.prompter-root::-webkit-scrollbar { width: 6px; }
.prompter-root::-webkit-scrollbar-thumb { background: #333344; border-radius: 3px; }
.prompter-inner { padding: 12px; box-sizing: border-box; }
.prompter-header {
    text-align: center;
    padding: 4px 0 10px;
    border-bottom: 1px solid rgba(18, 227, 255, 0.15);
    margin-bottom: 10px;
}
.prompter-title {
    font-size: 15px; font-weight: 800; letter-spacing: 2px;
    text-transform: uppercase;
    background: linear-gradient(135deg, #12E3FF, #4A6BFF);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin: 0;
}
.prompter-subtitle {
    font-size: 9px; color: #8B8BA3; letter-spacing: 2px;
    text-transform: uppercase; margin-top: 4px; font-weight: 600;
}
.prompter-card {
    background: #111118;
    border: 1px solid #4A6BFF;
    border-radius: 8px; padding: 10px 12px;
    margin-bottom: 12px; font-size: 10px; line-height: 1.4;
}
.prompter-badge {
    display: inline-block; font-size: 8px; font-weight: 800;
    letter-spacing: 1.5px; padding: 3px 6px; border-radius: 4px;
    background: #1A1A2E; color: #12E3FF; margin-bottom: 6px;
}
.prompter-row {
    display: flex; align-items: center; gap: 10px; margin: 8px 0;
    height: 26px;
}
.prompter-label {
    min-width: 100px; font-size: 11px; color: #8B8BA3;
    text-align: right; font-weight: 500;
}
.prompter-slider {
    min-width: 0;
    -webkit-appearance: none; appearance: none;
    flex: 1; height: 6px; border-radius: 3px;
    background: #111118; outline: none; cursor: pointer;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.5);
}
.prompter-slider::-webkit-slider-thumb {
    -webkit-appearance: none; width: 14px; height: 14px;
    border-radius: 50%; background: #12E3FF;
    border: 1px solid #4A6BFF; cursor: grab;
    box-shadow: 0 0 6px rgba(18, 227, 255, 0.5);
    margin-top: -4px;
}
.prompter-slider-val {
    min-width: 35px; text-align: right; font-size: 11px;
    font-family: monospace; color: #12E3FF; font-weight: 700;
}
.prompter-switch { display: flex; align-items: center; gap: 8px; cursor: pointer; flex: 1; }
.prompter-switch-text { font-size: 10px; font-weight: 700; color: #8B8BA3; width: 26px; text-align: right; }
.prompter-switch input { display: none; }
.prompter-switch-track { width: 32px; height: 16px; background: #111118; border-radius: 8px; position: relative; border: 1px solid #4A6BFF; }
.prompter-switch-thumb { width: 12px; height: 12px; background: #8B8BA3; border-radius: 50%; position: absolute; top: 1px; left: 2px; transition: 0.2s; }
.prompter-switch input:checked + .prompter-switch-text { color: #12E3FF; }
.prompter-switch input:checked ~ .prompter-switch-track { background: rgba(74, 107, 255, 0.2); }
.prompter-switch input:checked ~ .prompter-switch-track .prompter-switch-thumb { background: #12E3FF; transform: translateX(14px); box-shadow: 0 0 6px #12E3FF; }
.prompter-input { box-sizing: border-box; min-width: 0; width: 0; flex: 1; background: #111118; border: 1px solid #4A6BFF; color: #12E3FF; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; outline: none; }
`;
    document.head.appendChild(style);
}

function buildUI() {
    const el = document.createElement("div");
    el.className = "prompter-root";
    const inner = document.createElement("div");
    inner.className = "prompter-inner";
    el.appendChild(inner);

    let html = `
        <div class="prompter-header">
            <div class="prompter-title">Local Prompt Formatter</div>
            <div class="prompter-subtitle">Offline • Prompt Formatting</div>
        </div>
        <div class="prompter-card">
            <span class="prompter-badge">★ LOCAL PROMPT PIPELINE</span>
            <div style="color: #bbb; margin: 4px 0;">Appends prompt phrases for skin texture, natural lighting and quality using your selected settings.</div>
            <div style="color: #8B8BA3; font-style: italic; margin-top: 6px;">💡 Enter any non-blank text, adjust parameters, then queue prompt. Validation stays local.</div>
        </div>
    `;

    Object.entries(WIDGET_META).forEach(([wName, w]) => {
        html += `<div class="prompter-row" id="row_${wName}">
            <span class="prompter-label">${w.label}</span>`;

        if (w.type === "slider") {
            html += `
                <input type="range" class="prompter-slider" id="inp_${wName}" min="${w.min}" max="${w.max}" step="${w.step}">
                <span class="prompter-slider-val" id="val_${wName}"></span>`;
        } else if (w.type === "toggle") {
            html += `
                <label class="prompter-switch">
                    <input type="checkbox" id="inp_${wName}">
                    <span class="prompter-switch-text" id="val_${wName}">OFF</span>
                    <div class="prompter-switch-track"><div class="prompter-switch-thumb"></div></div>
                </label>`;
        } else if (w.type === "combo") {
            html += `<select class="prompter-input" id="inp_${wName}"></select>`;
        } else if (w.type === "text") {
            html += `<input type="text" class="prompter-input" id="inp_${wName}">`;
        }
        html += `</div>`;
    });

    inner.innerHTML = html;
    return el;
}

function getWidget(node, name) {
    return node.widgets?.find(w => w.name === name);
}

function hideDefaultWidget(w) {
    if (!w) return;
    w.hidden = true; w.type = "hidden"; w.computeSize = () => [0, -4];
    w.draw = function () { }; w.mouse = function () { return false; };
}

app.registerExtension({
    name: "LocalPromptFormatter.DashboardUI",
    nodeCreated(node) {
        if (node.comfyClass !== NODE_NAME) return;
        injectCSS();

        const paramNames = Object.keys(WIDGET_META);
        for (const name of paramNames) hideDefaultWidget(getWidget(node, name));

        const el = buildUI();
        const inner = el.querySelector(".prompter-inner");
        let contentH = 340;
        
        const widgetOptions = {
            serialize: false,
            hideOnZoom: false,
            // Keep the DOM overlay aligned after edits and canvas redraws.
            onDraw: widget => { widget.width = node.width ?? node.size[0]; },
            getMinHeight: () => contentH,
            getMaxHeight: () => contentH,
        };
        
        let domWidget = node.addDOMWidget("prompter_dashboard", "customwidget", el, widgetOptions);

        function measure() {
            if (inner.offsetHeight) contentH = inner.offsetHeight + 22;
        }

        const sizeObserver = new ResizeObserver(() => {
            const previous = contentH;
            measure();
            if (contentH !== previous) fitHeight();
        });
        sizeObserver.observe(inner);
        const previousRemove = node.onRemoved;
        node.onRemoved = function (...args) {
            sizeObserver.disconnect();
            return previousRemove?.apply(this, args);
        };
        if (typeof domWidget.computeLayoutSize === "function") {
            const layoutSize = domWidget.computeLayoutSize.bind(domWidget);
            domWidget.computeLayoutSize = target => ({ ...layoutSize(target), minWidth: 400 });
        }
        for (const eventName of ["input", "change"]) {
            el.addEventListener(eventName, () => node.setDirtyCanvas?.(true, true));
        }

        function fitHeight() {
            requestAnimationFrame(() => {
                measure();
                if (!inner.offsetHeight) return;
                const fit = node.computeSize();
                const width = Math.min(Math.max(node.size[0], 400), 800);
                node.setSize([width, fit[1]]);
                node.setDirtyCanvas?.(true, true);
            });
        }

        node.color = "#0A0A0F";
        node.bgcolor = "#1A1A24";

        Object.entries(WIDGET_META).forEach(([name, meta]) => {
            const domInp = el.querySelector(`#inp_${name}`);
            const domVal = el.querySelector(`#val_${name}`);
            const lgW = getWidget(node, name);
            if (!domInp || !lgW) return;
            if (name === "required_text") { domInp.required = true; domInp.placeholder = "Enter any text"; }

            if (meta.type === "slider") {
                domInp.addEventListener("input", () => {
                    lgW.value = parseFloat(domInp.value);
                    if (lgW.callback) lgW.callback(lgW.value);
                    if (domVal) domVal.textContent = Number(lgW.value).toFixed(2);
                });
            } else if (meta.type === "toggle") {
                domInp.addEventListener("change", (e) => {
                    lgW.value = e.target.checked;
                    if (lgW.callback) lgW.callback(lgW.value);
                    if (domVal) domVal.textContent = lgW.value ? "ON" : "OFF";
                });
            } else if (meta.type === "combo") {
                (lgW.options?.values || []).forEach(opt => {
                    const o = document.createElement("option"); o.value = opt; o.innerText = opt;
                    domInp.appendChild(o);
                });
                domInp.addEventListener("change", (e) => {
                    lgW.value = e.target.value;
                    if (lgW.callback) lgW.callback(lgW.value);
                });
            } else if (meta.type === "text") {
                domInp.addEventListener("input", (e) => {
                    lgW.value = e.target.value;
                    if (lgW.callback) lgW.callback(lgW.value);
                });
            }
        });

        function syncFromWidgets() {
            Object.entries(WIDGET_META).forEach(([name, meta]) => {
                const domInp = el.querySelector(`#inp_${name}`);
                const domVal = el.querySelector(`#val_${name}`);
                const lgW = getWidget(node, name);
                if (!domInp || !lgW) return;

                if (meta.type === "slider") {
                    domInp.value = lgW.value;
                    if (domVal) domVal.textContent = Number(lgW.value).toFixed(2);
                } else if (meta.type === "toggle") {
                    domInp.checked = !!lgW.value;
                    if (domVal) domVal.textContent = lgW.value ? "ON" : "OFF";
                } else {
                    domInp.value = lgW.value;
                }
            });
        }

        node.onConfigure = function () {
            setTimeout(() => {
                syncFromWidgets();
                fitHeight();
            }, 80);
        };

        setTimeout(() => {
            syncFromWidgets();
            fitHeight();
        }, 150);
    },
});