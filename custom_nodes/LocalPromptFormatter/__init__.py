"""Offline ComfyUI prompt formatter with a required, locally checked text field."""


class LocalPromptFormatter:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "required_text": ("STRING", {"default": "", "tooltip": "Enter any non-blank text. Checked locally only."}),
            "base_prompt": ("STRING", {"multiline": True, "default": "a beautiful woman"}),
            "master_strength": ("FLOAT", {"default": 0.85, "min": 0.0, "max": 1.0, "step": 0.01, "display": "slider"}),
            "real_skin_texture": ("BOOLEAN", {"default": True, "label_on": "ON", "label_off": "OFF"}),
            "natural_lighting": ("BOOLEAN", {"default": True, "label_on": "ON", "label_off": "OFF"}),
            "base_quality": (["2x", "4x", "8x"],),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("enhanced_prompt",)
    FUNCTION = "process"
    CATEGORY = "Local/Prompt"

    @classmethod
    def VALIDATE_INPUTS(cls, required_text):
        if not isinstance(required_text, str) or not required_text.strip():
            return "Required Text: enter any non-blank text before running the node."
        return True

    def process(self, required_text, base_prompt, master_strength, real_skin_texture, natural_lighting, base_quality):
        valid = self.VALIDATE_INPUTS(required_text)
        if valid is not True:
            raise ValueError(valid)
        parts = [base_prompt]
        if real_skin_texture:
            parts.append(f"(raw photo, ultra realistic skin texture, subsurface scattering:{master_strength})")
        if natural_lighting:
            parts.append(f"(natural lighting, golden hour aesthetics, ray tracing:{master_strength})")
        parts.append({
            "2x": "(masterpiece, high quality)",
            "4x": "(masterpiece, 4k resolution)",
            "8x": "(masterpiece, 8k resolution, ultra high definition)",
        }[base_quality])
        return (", ".join(parts),)


WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {"LocalPromptFormatter": LocalPromptFormatter}
NODE_DISPLAY_NAME_MAPPINGS = {"LocalPromptFormatter": "Local Prompt Formatter"}
