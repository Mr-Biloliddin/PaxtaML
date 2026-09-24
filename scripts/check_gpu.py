"""Проверка, что PyTorch видит GPU и CUDA работает."""
import sys

import torch


def main() -> int:
    print(f"PyTorch:        {torch.__version__}")
    print(f"CUDA (сборка):  {torch.version.cuda}")
    print(f"cuDNN:          {torch.backends.cudnn.version()}")

    if not torch.cuda.is_available():
        print("\n[!] CUDA недоступна. Проверьте драйвер NVIDIA (nvidia-smi) и что "
              "torch установлен с индекса download.pytorch.org/whl/cuXXX.")
        return 1

    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        print(f"GPU {i}:          {p.name}, {p.total_memory / 1024**3:.1f} GB, "
              f"compute capability {p.major}.{p.minor}")

    print(f"bf16:           {torch.cuda.is_bf16_supported()}")

    x = torch.randn(2048, 2048, device="cuda")
    with torch.autocast("cuda", dtype=torch.float16):
        y = x @ x
    torch.cuda.synchronize()
    print(f"\nТестовое умножение матриц на GPU: OK ({y.dtype})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
