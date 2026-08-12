# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

## Elektor Web Dashboard Components

This React + TypeScript + Vite frontend provides the interactive control suite for the **Elektor Universal PDF & Rendergit Synthetic Dataset Pipeline**:

- **SectionConfig**: Handles pipeline parameters, generation language, persona selection, vision OCR settings (`deepseek-ocr:3b-bf16`), and **Parallel Sharding** controls (shards count, GPU ports like `11434,11435`).
- **SectionTerminal**: Live streaming console log output with intelligent **Auto-Scroll-Lock** capability to preserve scroll position during active execution.
- **ProjectExplorer Modal**: Integrated System Prompt, Persona Editor, and multi-project dataset merger.
- **HF & Cloud GPU Modal**: 2-stage Dry-Run audit and Hugging Face Hub dataset uploader + RunPod/Unsloth cloud payload generator.
