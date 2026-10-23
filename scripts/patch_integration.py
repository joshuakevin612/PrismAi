from pathlib import Path

# Update backend/model_client.py mock command to not recursively invoke pytest
mc = Path("backend/model_client.py")
text = mc.read_text(encoding="utf-8")
text = text.replace('commands=[["pytest", "tests/"]]', 'commands=[["python", "-c", "print(\'Remediation verified\')"]]')
mc.write_text(text, encoding="utf-8")
print("Updated backend/model_client.py")
