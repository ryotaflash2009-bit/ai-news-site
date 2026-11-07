"""Vercel 版の入り口。ページが見られたときに、その場でニュースを取得してページを作る。

vercel.json の rewrites で、/ と /chatgpt.html などへのアクセスがここに届く。
中身は手元で動かすサーバー(app.py)とまったく同じ。取得結果は Vercel の配信網に数分だけ保存して使い回す。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402,F401  (Vercel はこの app を呼び出す)
