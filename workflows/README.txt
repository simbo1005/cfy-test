Put ordinary ComfyUI workflow JSON exports in this folder before building.
Example:
  workflows/My workflow.json
  workflows/Image editing/Another workflow.json

Export using the normal workflow export in ComfyUI, not the API-format export.
Only .json files are installed. This README is not copied into the UI folder.
Startup copies them to /workspace/ComfyUI/user/default/workflows/ and preserves
subfolders. They appear in the Workflows sidebar (refresh the list/browser).
Existing destination files, including user-edited copies, are never overwritten.
For an updated bundled workflow, use a new filename or deliberately remove the
old destination copy before restarting. Back up edits you want to keep.

For RunPod, add files here before building a new image. With local Compose,
this folder is mounted directly; add files and restart the service.
On a running pod, you can also upload JSON files through Jupyter directly to:
  user/default/workflows/

Workflows refer to models/custom nodes; they do not bundle or install them.
Ensure models.json and the selected node profile cover their requirements.
