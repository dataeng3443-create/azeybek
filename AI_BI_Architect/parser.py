# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk: modülün asıl adı artık `pbit_parser`.

Python 3.9'da `parser` adında yerleşik bir modül olduğu için `import parser`
bu dosya yerine onu yüklüyordu. Yeni kod `pbit_parser`'ı kullanır; bu dosya
eski betikler kırılmasın diye duruyor ve silinebilir.
"""

from pbit_parser import *  # noqa: F401,F403
from pbit_parser import PBITParser  # noqa: F401
