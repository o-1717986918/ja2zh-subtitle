# Model and dependency notice

The source code is distributed under the MIT License. Model weights are governed by their own licenses.

The Windows offline installer includes the `Systran/faster-whisper-medium` CTranslate2 model so speech recognition works without a model download. Its Hugging Face repository declares the MIT License and identifies it as a conversion of `openai/whisper-medium`. The source-only project checkout may also contain locally downloaded models under `models/`; those files are not part of the source distribution.

Default model identifiers:

- `Systran/faster-whisper-medium`: MIT; included in the Windows offline installer.
- `openai/whisper-*` / other faster-whisper conversions: review the model card and repository license before redistribution.
- `facebook/nllb-200-distilled-600M`: CC-BY-NC; its model card describes it as a research model and not released for production deployment.
- `Qwen/Qwen3-0.6B` and `Qwen/Qwen3-1.7B`: Apache-2.0 at the time this project configuration was prepared.

Before commercial use or redistribution, verify the current license and acceptable-use terms for every selected model and dependency and retain the notices shipped with the installer.

The bundled `NotoSansCJKjp-Regular.otf` and `NotoSansCJKsc-Regular.otf` fonts are
distributed under the SIL Open Font License 1.1. The complete font license is
included at `assets/fonts/OFL.txt`.
