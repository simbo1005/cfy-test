FROM ubuntu:24.04 AS base
ARG COMFYUI_COMMIT=426f5eea52a7ece1dd599fff4cb6cd1f352ddd24
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH \
    NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv git ca-certificates tini libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY constraints.txt /opt/constraints.txt
RUN python3 -m venv /opt/venv \
    && python -m pip install --upgrade pip \
    && python -m pip install -c /opt/constraints.txt torch torchvision huggingface_hub==2.4.0 \
    && git init /opt/comfyui-seed \
    && cd /opt/comfyui-seed \
    && git remote add origin https://github.com/Comfy-Org/ComfyUI.git \
    && git fetch --depth 1 origin "$COMFYUI_COMMIT" \
    && git checkout --detach FETCH_HEAD \
    && python -m pip install -c /opt/constraints.txt -r requirements.txt -r manager_requirements.txt \
    && printf '%s\n' "$COMFYUI_COMMIT" > /opt/comfyui-seed/.image-comfyui-commit
# Keep notebook dependencies outside ComfyUI's inference environment.
RUN python3 -m venv /opt/jupyter \
    && /opt/jupyter/bin/python -m pip install jupyterlab==4.6.4 \
       jupyter_server_terminals==0.5.4 terminado==0.18.1 ipykernel==7.4.0 \
    && /opt/jupyter/bin/jupyter server extension enable --py jupyter_server_terminals --sys-prefix \
    && /opt/jupyter/bin/python -m ipykernel install --sys-prefix --name python3 --display-name "Python 3" \
    && /opt/jupyter/bin/python -m pip check
COPY custom_nodes/ /opt/comfyui-seed/custom_nodes/
COPY nodes.lock.json install_nodes.py start.sh launch.py download_models.py models.json install_workflows.py /opt/template/
# Validate syntax and manifest semantics at build time without downloading weights.
RUN python /opt/template/download_models.py --manifest /opt/template/models.json --validate-only
COPY workflows/ /opt/template/workflows/
WORKDIR /workspace
EXPOSE 8188 8888
ENTRYPOINT ["/usr/bin/tini", "-s", "-g", "--"]
CMD ["/bin/bash", "/opt/template/start.sh"]
HEALTHCHECK --start-period=180s --interval=30s --timeout=5s --retries=3 \
    CMD ["/opt/venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=4)"]

FROM base AS curated
RUN apt-get update && apt-get install -y --no-install-recommends build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python /opt/template/install_nodes.py \
    && python -m pip check \
    && python -m pip freeze > /opt/comfyui-seed/image-packages.txt

# Both profiles include the local formatter; curated adds the six optional packs.
FROM base AS vanilla
RUN python -m pip check \
    && python -m pip freeze > /opt/comfyui-seed/image-packages.txt
