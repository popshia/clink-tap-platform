"""
檢查每行 CSV 的欄位數是否符合預期。

格式規格：
  欄1 : 物件 ID
  欄2 : 起始 frame (col index 1)
  欄3 : 結束 frame (col index 2)
  欄4~6: 固定欄位
  欄7起 : 座標資料，每 8 個值 = 1 個 frame

期望欄位數 = 6 (固定) + (結束frame - 起始frame + 1) * 8
"""

import argparse
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FIXED_COLS = 6
COORDS_PER_FRAME = 8


def check_file(filepath: str, encoding: str = "utf-8") -> list[str]:
    errors = []

    try:
        with open(filepath, "r", encoding=encoding) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return [f"找不到檔案：{filepath}"]
    except UnicodeDecodeError:
        return check_file(filepath, encoding="big5")

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue

        cols = line.split(",")
        actual = len(cols)

        try:
            start_frame = int(cols[1])
            end_frame = int(cols[2])
        except IndexError:
            errors.append(f"第 {line_num} 行：欄位數不足，無法讀取起始/結束 frame")
            continue
        except ValueError:
            errors.append(
                f"第 {line_num} 行：起始/結束 frame 無法轉為整數 "
                f"(col2={cols[1]!r}, col3={cols[2]!r})"
            )
            continue

        if end_frame < start_frame:
            errors.append(
                f"第 {line_num} 行：結束 frame ({end_frame}) < 起始 frame ({start_frame})"
            )
            continue

        num_frames = end_frame - start_frame + 1
        expected = FIXED_COLS + num_frames * COORDS_PER_FRAME

        if actual != expected:
            diff = actual - expected
            errors.append(
                f"第 {line_num} 行：預期 {expected} 欄 "
                f"(frame {start_frame}~{end_frame}，共 {num_frames} frames × {COORDS_PER_FRAME})，"
                f"實際 {actual} 欄，差 {diff:+d}"
            )

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="檢查交通軌跡 CSV 每行長度是否符合 frame 範圍"
    )
    parser.add_argument("filepath", help="CSV 檔案路徑")
    parser.add_argument(
        "--encoding", default="utf-8", help="檔案編碼 (預設 utf-8，失敗會自動嘗試 big5)"
    )
    parser.add_argument("-o", "--output", help="將結果輸出到指定檔案 (UTF-8)")
    args = parser.parse_args()

    print(f"檢查檔案：{args.filepath}")
    errors = check_file(args.filepath, args.encoding)

    lines = []
    if not errors:
        lines.append("[OK] 全部行長度正確")
    else:
        lines.append(f"[FAIL] 發現 {len(errors)} 個問題：")
        for msg in errors:
            lines.append(f"  {msg}")

    for line in lines:
        print(line)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"報告已寫入：{args.output}")

    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
