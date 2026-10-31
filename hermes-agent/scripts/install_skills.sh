#!/usr/bin/env bash
# Installer & verifier script for Elektor Hermes Agent Skills.
# Usage:
#   ./install_skills.sh --check                 # Verify local skills without modifying $HERMES_HOME
#   ./install_skills.sh --link [--force]        # Symlink skills into ${HERMES_HOME:-$HOME/.hermes}/skills/data/
#   ./install_skills.sh --copy [--force]        # Copy skills (including standalone CLI) into ${HERMES_HOME:-$HOME/.hermes}/skills/data/
#   ./install_skills.sh --uninstall             # Remove installed Elektor skills from ${HERMES_HOME:-$HOME/.hermes}/skills/data/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_AGENT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${HERMES_AGENT_DIR}/.." && pwd)"
SOURCE_SKILLS_DIR="${HERMES_AGENT_DIR}/skills/data"
TARGET_HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
TARGET_DATA_DIR="${TARGET_HERMES_HOME}/skills/data"

PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="python3"
fi

SKILLS=(
    "elektor-dataset-pipeline"
    "elektor-ocr-layout"
    "elektor-rag-memory"
    "elektor-dataset-curation"
)

MODE="${1:---check}"
FORCE="${2:-}"

case "${MODE}" in
    --check)
        echo "[Elektor Hermes Installer] Validating skills in ${SOURCE_SKILLS_DIR}..."
        "${PYTHON_BIN}" "${SCRIPT_DIR}/elektor_hermes_cli.py" validate-skills --skills-dir "${HERMES_AGENT_DIR}/skills"
        echo "[Elektor Hermes Installer] Target HERMES_HOME: ${TARGET_HERMES_HOME}"
        for skill in "${SKILLS[@]}"; do
            dest="${TARGET_DATA_DIR}/${skill}"
            if [[ -L "${dest}" ]]; then
                echo "  [INSTALLED:SYMLINK] ${skill} -> $(readlink -f "${dest}")"
            elif [[ -d "${dest}" ]]; then
                echo "  [INSTALLED:COPY]    ${skill} (${dest})"
            else
                echo "  [NOT INSTALLED]     ${skill} (ready in ${SOURCE_SKILLS_DIR}/${skill})"
            fi
        done
        ;;
    --link)
        "${PYTHON_BIN}" "${SCRIPT_DIR}/elektor_hermes_cli.py" validate-skills --skills-dir "${HERMES_AGENT_DIR}/skills" >/dev/null
        mkdir -p "${TARGET_DATA_DIR}"
        for skill in "${SKILLS[@]}"; do
            src="${SOURCE_SKILLS_DIR}/${skill}"
            dest="${TARGET_DATA_DIR}/${skill}"
            if [[ -L "${dest}" ]]; then
                rm -f "${dest}"
            elif [[ -e "${dest}" ]]; then
                if [[ "${FORCE}" == "--force" ]]; then
                    rm -rf "${dest}"
                else
                    echo "Error: ${dest} already exists and is not a symlink. Re-run with '--link --force' to replace." >&2
                    exit 1
                fi
            fi
            ln -s "${src}" "${dest}"
            echo "Linked ${skill} -> ${dest}"
        done
        ;;
    --copy)
        "${PYTHON_BIN}" "${SCRIPT_DIR}/elektor_hermes_cli.py" validate-skills --skills-dir "${HERMES_AGENT_DIR}/skills" >/dev/null
        mkdir -p "${TARGET_DATA_DIR}"
        for skill in "${SKILLS[@]}"; do
            src="${SOURCE_SKILLS_DIR}/${skill}"
            dest="${TARGET_DATA_DIR}/${skill}"
            if [[ -L "${dest}" ]]; then
                rm -f "${dest}"
            elif [[ -e "${dest}" ]]; then
                if [[ "${FORCE}" == "--force" ]]; then
                    rm -rf "${dest}"
                else
                    echo "Error: ${dest} already exists. Re-run with '--copy --force' to overwrite." >&2
                    exit 1
                fi
            fi
            cp -R "${src}" "${dest}"
            cp -f "${SCRIPT_DIR}/elektor_hermes_cli.py" "${dest}/scripts/elektor_hermes_cli.py"
            chmod +x "${dest}/scripts/elektor_hermes_cli.py"
            echo "Copied standalone ${skill} -> ${dest}"
        done
        ;;
    --uninstall)
        for skill in "${SKILLS[@]}"; do
            dest="${TARGET_DATA_DIR}/${skill}"
            if [[ -L "${dest}" ]]; then
                rm -f "${dest}"
                echo "Removed symlink ${dest}"
            elif [[ -d "${dest}" ]]; then
                rm -rf "${dest}"
                echo "Removed directory ${dest}"
            fi
        done
        ;;
    *)
        echo "Usage: $0 [--check|--link [--force]|--copy [--force]|--uninstall]"
        exit 1
        ;;
esac
