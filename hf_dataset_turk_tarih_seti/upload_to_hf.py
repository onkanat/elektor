import os
import sys
from pathlib import Path
from huggingface_hub import HfApi, create_repo

def main():
    repo_id = "onkanat/turk-tarihi-1931-sft-dpo"
    local_dir = Path(__file__).parent.resolve()
    
    print(f"=== Hugging Face Dataset Push Orchestrator ===")
    print(f"Target Repo: https://huggingface.co/datasets/{repo_id}")
    print(f"Local Directory: {local_dir}\n")
    
    api = HfApi()
    
    try:
        user_info = api.whoami()
        print(f"✓ Authenticated as HF User: '{user_info.get('name') or user_info.get('fullname')}'")
    except Exception as e:
        print(f"❌ Error: Hugging Face authentication failed: {e}")
        sys.exit(1)
        
    try:
        create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        print(f"✓ Dataset repository '{repo_id}' verified on Hugging Face Hub.")
    except Exception as e:
        print(f"Warning creating repository: {e}")

    print("Uploading dataset card (README.md), cover image, and data files...")
    try:
        api.upload_file(
            path_or_fileobj=str(local_dir / "README.md"),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="dataset"
        )
        api.upload_file(
            path_or_fileobj=str(local_dir / "cover_1931.png"),
            path_in_repo="cover_1931.png",
            repo_id=repo_id,
            repo_type="dataset"
        )
        api.upload_folder(
            folder_path=str(local_dir / "data"),
            path_in_repo="data",
            repo_id=repo_id,
            repo_type="dataset"
        )
        print("\n🎉 SUCCESS! Dataset card & data files published to Hugging Face!")
        print(f"🔗 Dataset Repository URL: https://huggingface.co/datasets/{repo_id}")
    except Exception as e:
        print(f"❌ Error during upload: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
