import os
import random
import re
from typing import Optional

try:
    import numpy as np
except ImportError:
    np = None

try:
    import torch
except ImportError:
    torch = None


def set_seed(seed: int) -> None:
    random.seed(seed)
    if np is not None:
        np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def auto_device(device: Optional[str] = None):
    if torch is None:
        raise RuntimeError("torch is required for auto_device")
    if device is not None:
        return torch.device(device)
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")

# this is to extract answer in \boxed{}
def extract_gsm8k_answer(text: str) -> Optional[str]:
    boxes = re.findall(r"\\boxed\{([^}]*)\}", text)
    if boxes:
        content = boxes[-1]
        number = re.search(r"[-+]?\d+(?:\.\d+)?", content)
        return number.group(0) if number else content.strip()

    numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    if numbers:
        return numbers[-1]
    return None


def extract_gold(text: str) -> Optional[str]:
    match = re.search(r"####\s*([-+]?\d+(?:\.\d+)?)", text)
    return match.group(1) if match else None


def normalize_answer(ans: Optional[str]) -> Optional[str]:
    if ans is None:
        return None
    return ans.strip().lower()


def extract_markdown_python_block(text: str) -> Optional[str]:
    pattern = r"```python(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
    if matches:
        return matches[-1].strip()
    return None


# to run python
import traceback
from multiprocessing import Process, Manager


def trim_text_to_token_budget(tokenizer, text: str, max_tokens: int, keep: str = "tail") -> str:
    """Trim text by tokenizer IDs when available; fall back to a 4 chars/token estimate."""
    if text is None or max_tokens is None or max_tokens < 0:
        return text
    if max_tokens == 0:
        return ""
    if tokenizer is not None:
        encoded = tokenizer(text, add_special_tokens=False)
        ids = encoded.get("input_ids", [])
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        if len(ids) <= max_tokens:
            return text
        kept_ids = ids[:max_tokens] if keep == "head" else ids[-max_tokens:]
        return tokenizer.decode(kept_ids, skip_special_tokens=False)

    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] if keep == "head" else text[-max_chars:]


def run_with_timeout(code, timeout):
    def worker(ns, code):
        try:
            local_ns = {}
            exec(code, local_ns)
            ns['ok'] = True
            ns['error'] = None
        except Exception:
            ns['ok'] = False
            ns['error'] = traceback.format_exc()
    with Manager() as manager:
        ns = manager.dict()
        p = Process(target=worker, args=(ns, code))
        p.start()
        p.join(timeout)
        if p.is_alive():
            p.terminate()
            ns['ok'] = False
            ns['error'] = f"TimeoutError: Execution exceeded {timeout} seconds"
        return ns.get('ok', False), ns.get('error', None)
