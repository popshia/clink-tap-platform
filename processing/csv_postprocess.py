import argparse
import csv
import math
import multiprocessing
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from loguru import logger
from tqdm import tqdm


class TrajectoryConfig:
    # --- 軌跡處理參數統一管理區 ---

    # 1. 軌跡平滑參數
    SMOOTH_WINDOW = 5  # 移動平均的窗口大小，數值越大軌跡越平滑，但反應會變遲鈍
    LOOKAHEAD_FRAMES = 5  # 計算移動向量時跨越的幀數 (避免相鄰幀抖動)

    # 2. 動態比例尺參數 (以車長為基準的比例，適應不同空拍高度)
    MIN_MOVE_RATIO = 0.05  # 最小移動距離比例 (移動超過車長的 5% 才算有效移動)
    ESCAPE_RATIO = 0.5  # 巨觀逃逸半徑：必須離開起點超過「半個車身」，才認定為真實起步 (免疫漫長停等的抖動)
    ABSOLUTE_ESCAPE_PX = 10.0  # 保底離開距離 (像素)
    ABSOLUTE_MIN_MOVE_PX = 2.0  # 保底絕對最小移動距離 (像素)

    # 3. 防飄移與異常判斷參數
    # 【強制長邊鎖定 — 兩階段設計】
    # 大型車進入畫面「邊緣期」時，偵測框可能被截切而使長寬比失真，不能強制長邊。
    # 但完整進入畫面之後，車頭「一定」在短邊（前臉），即物理長邊 = 車身軸線，可安全強制。
    # ‣ FORCE_LONG_AXIS_TYPES       : 全程強制長邊 (機車幾何穩定，不受邊緣截切)
    # ‣ FORCE_LONG_AXIS_STABLE_TYPES: 穩定期才強制長邊 (大型車完整入畫後 + 機車)；
    #                                  init_idx 之前的回補期仍用 reference 軸，避免邊緣截切誤判
    FORCE_LONG_AXIS_TYPES = ["m"]
    FORCE_LONG_AXIS_STABLE_TYPES = ["b", "t", "m"]

    # 針對不同車種給予不同的最大轉向限制，超過此角度視為框格變形的假位移 (側滑或斷軌前兆)
    MAX_TURN_ANGLE_MAP = {
        "b": 45.0,  # 大客車：轉向慢、框格大，嚴格限制防側滑與斷軌
        "t": 45.0,  # 大貨車：轉向慢、框格大，嚴格限制防側滑與斷軌
        "c": 90.0,  # 小客車：轉向適中，容忍 90 度校正
        "m": 120.0,  # 機車：配合臺灣待轉區急彎特性，放寬至 120 度。因已有 FORCE_LONG_AXIS 保護，不怕車頭標到側邊！
    }
    DEFAULT_MAX_TURN_ANGLE = 60.0  # 若遇到未知車種的預設值

    # 各車種倒車判定角度。注意：'m' 刻意與 MAX_TURN_ANGLE_MAP['m'] 相同 (120°)，
    # 代表機車沒有「異常側滑緩衝區」——由 FORCE_LONG_AXIS 保護，角度要麼是正常轉彎，要麼直接倒車。
    REVERSE_ANGLE_MAP = {
        "b": 120.0,
        "t": 120.0,
        "c": 120.0,
        "m": 120.0,
    }
    DEFAULT_REVERSE_ANGLE = 120.0

    # 5. 【持續側滑偵測】防止初始車頭誤判後被永久鎖定在側邊
    # 大型車進入畫面時，偵測框不穩定旋轉會導致初始車頭差 90°，之後所有幀的正常前進
    # 都會落在「異常側滑區」，而被系統永遠鎖死在錯誤方向。
    # 若連續 N 幀都在側滑區且位移方向一致 (非隨機抖動)，視為車頭誤判並觸發回溯重設。
    PERSISTENT_ANOMALY_THRESHOLD = (
        10  # 異常幀數門檻（可跨靜止幀累積，故可低於連續判斷所需）
    )
    MOTION_DIRECTIONALITY_MIN = (
        0.70  # 位移一致性門檻：累積向量長 / 各幀位移之和；越接近 1.0 代表越是直線前進
    )
    EDGE_FRAME_LENGTH_RATIO = (
        0.65  # 當幀長邊 < 中位數的此比例時，視為邊緣截切幀，退回 motion-based 軸選擇
    )
    # (對稱保護進場與離場：截切時框格長寬比失真，強制長邊反而選錯軸)

    # 4. 【最新升級：動態倒車距離極限 (倍數 * 基準車長)】
    # 避免起步往後滑導致整條軌跡 180 度翻轉，超過此距離視為「假倒車」並啟動回溯校正
    MAX_REVERSE_RATIO_MAP = {
        "m": 3.0,  # 機車極短，從停車格嚕出來退個 3 倍車長很合理
        "c": 2.0,  # 汽車路邊停車，給予 2 倍車長的寬容度
        "b": 1.0,  # 大客車幾乎不會長距離倒車，嚴格限制
        "t": 1.0,  # 大貨車同上
    }
    DEFAULT_REVERSE_RATIO = 2.0


def smooth_trajectory(centers, window_size):
    """使用移動平均平滑中心點軌跡"""
    pad_width = window_size // 2
    padded = np.pad(centers, ((pad_width, pad_width), (0, 0)), mode="edge")
    # 前綴和：cs[i+W] - cs[i] = padded[i:i+W] 的累積和，除以 W 得移動平均，省去 Python 迴圈
    cs = np.cumsum(np.vstack([np.zeros((1, centers.shape[1])), padded]), axis=0)
    return (
        cs[window_size : window_size + len(centers)] - cs[: len(centers)]
    ) / window_size


def calculate_angle(v1, v2):
    """計算兩個向量的夾角(度)"""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    cos_theta = dot_product / (norm_v1 * norm_v2)
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    return math.degrees(math.acos(cos_theta))


def get_vehicle_axis(pts, center, reference_vector=None, force_long_axis=False):
    """
    獲取車身軸線。
    若 force_long_axis 為 True，則無視軌跡方向，絕對鎖定實體幾何長邊！
    （此函數保留供外部呼叫；process_single_vehicle 內部改用預計算軸以提升效能）
    """
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    sorted_indices = np.argsort(angles)
    poly = pts[sorted_indices]

    v01 = poly[1] - poly[0]
    v12 = poly[2] - poly[1]
    v23 = poly[3] - poly[2]
    v30 = poly[0] - poly[3]

    axis_A = (v01 - v23) / 2.0
    axis_B = (v12 - v30) / 2.0

    len_A = np.linalg.norm(axis_A)
    len_B = np.linalg.norm(axis_B)
    dir_A = axis_A / len_A if len_A > 0 else np.array([1.0, 0.0])
    dir_B = axis_B / len_B if len_B > 0 else np.array([1.0, 0.0])

    if force_long_axis:
        return dir_A if len_A > len_B else dir_B

    if reference_vector is not None and np.linalg.norm(reference_vector) > 0:
        dot_A = abs(np.dot(dir_A, reference_vector))
        dot_B = abs(np.dot(dir_B, reference_vector))
        return dir_A if dot_A > dot_B else dir_B
    else:
        return dir_A if len_A > len_B else dir_B


def align_axis_to_reference(coords_i, center_i, reference, force_long):
    """取車身軸線並對齊至參考方向（dot < 0 則翻轉 180°）"""
    axis = get_vehicle_axis(
        coords_i, center_i, reference_vector=reference, force_long_axis=force_long
    )
    return axis if np.dot(axis, reference) >= 0 else -axis


# ── 多行程工作者（module-level，確保可被 pickle）────────────────────────────────

_mp_config = None  # 由 _worker_init 設定，避免每次 IPC 序列化 config 的開銷


def _worker_init(config):
    """Pool 初始化：在每個工作行程中設置共用 config"""
    global _mp_config
    _mp_config = config


def _process_row_worker(args):
    """多行程工作者：處理單台車（含例外捕捉，確保不因單台失敗而中斷整批）"""
    index, row = args
    try:
        row = [item for item in row if item.strip() != ""]
        if len(row) < 6:
            return None
        return process_single_vehicle(row, _mp_config)
    except Exception as e:
        logger.warning(
            f"第 {index} 筆資料 (ID: {row[0] if row else '?'}) 處理失敗: {e}"
        )
        return row  # 返回原始資料，保留格式


def process_single_vehicle(row_data, config):
    """處理單台車的軌跡資料（向量化優化版）"""
    # 行人直接回傳原資料，不進行角點重新排序
    if len(row_data) >= 6 and row_data[5].strip().lower() == "p":
        return row_data

    meta_info = row_data[:6]
    v_type = meta_info[5].strip().lower()

    force_long = v_type in config.FORCE_LONG_AXIS_TYPES
    force_long_stable = v_type in config.FORCE_LONG_AXIS_STABLE_TYPES
    max_turn_angle = config.MAX_TURN_ANGLE_MAP.get(
        v_type, config.DEFAULT_MAX_TURN_ANGLE
    )
    reverse_angle = config.REVERSE_ANGLE_MAP.get(v_type, config.DEFAULT_REVERSE_ANGLE)
    max_reverse_ratio = config.MAX_REVERSE_RATIO_MAP.get(
        v_type, config.DEFAULT_REVERSE_RATIO
    )

    coords_raw = row_data[6:]
    num_frames = len(coords_raw) // 8
    if num_frames == 0:
        return row_data

    coords = np.array(coords_raw, dtype=float).reshape(num_frames, 4, 2)
    centers = np.mean(coords, axis=1)
    smoothed_centers = smooth_trajectory(centers, config.SMOOTH_WINDOW)
    _ni = np.arange(num_frames)  # 共用行索引，後面多處重複用到

    # ── 1. 預計算所有幀的車身軸線（向量化，取代逐幀 arctan2 + argsort + norm）──────
    # 等同於對每一幀執行 get_vehicle_axis，但改用 numpy 廣播一次完成，省去 Python 迴圈
    rel_pts = coords - centers[:, np.newaxis, :]  # (N,4,2) 以中心為原點的相對座標
    pt_angles = np.arctan2(rel_pts[:, :, 1], rel_pts[:, :, 0])  # (N,4) 偏角
    poly_all = coords[
        _ni[:, None], np.argsort(pt_angles, axis=1)
    ]  # (N,4,2) 逆時針排序角點
    v01_a = poly_all[:, 1] - poly_all[:, 0]  # (N,2)
    v12_a = poly_all[:, 2] - poly_all[:, 1]
    v23_a = poly_all[:, 3] - poly_all[:, 2]
    v30_a = poly_all[:, 0] - poly_all[:, 3]
    pre_axis_A = (v01_a - v23_a) * 0.5  # (N,2) 對邊平均軸 A
    pre_axis_B = (v12_a - v30_a) * 0.5  # (N,2) 對邊平均軸 B
    pre_len_A = np.linalg.norm(pre_axis_A, axis=1)  # (N,)
    pre_len_B = np.linalg.norm(pre_axis_B, axis=1)
    pre_dir_A = (
        pre_axis_A / np.where(pre_len_A > 0, pre_len_A, 1.0)[:, None]
    )  # (N,2) 單位向量
    pre_dir_B = pre_axis_B / np.where(pre_len_B > 0, pre_len_B, 1.0)[:, None]

    # ── 2. 向量化計算各幀長邊（取代 Python for loop）─────────────────────────────
    edge01 = np.linalg.norm(coords[:, 1] - coords[:, 0], axis=1)  # (N,)
    edge12 = np.linalg.norm(coords[:, 2] - coords[:, 1], axis=1)
    lengths = np.maximum(edge01, edge12)  # (N,)
    vehicle_length = float(np.median(lengths))

    dynamic_min_move = max(
        config.ABSOLUTE_MIN_MOVE_PX, vehicle_length * config.MIN_MOVE_RATIO
    )
    escape_radius = max(config.ABSOLUTE_ESCAPE_PX, vehicle_length * config.ESCAPE_RATIO)
    max_reverse_dist = vehicle_length * max_reverse_ratio

    target_indices = np.minimum(_ni + config.LOOKAHEAD_FRAMES, num_frames - 1)
    local_motions = smoothed_centers[target_indices] - smoothed_centers  # (N,2)
    local_motion_norms = np.linalg.norm(
        local_motions, axis=1
    )  # (N,) 預計算，避免迴圈內重複 norm

    front_vectors = np.zeros((num_frames, 2))

    # ── 3. 快速軸對齊閉包（捕捉預計算結果，取代 align_axis_to_reference 的逐幀計算）──
    def _align(i, reference, use_force_long):
        """利用預計算軸選軸並對齊參考方向，等同 align_axis_to_reference 但不重複計算 arctan2/argsort"""
        if use_force_long:
            ax = pre_dir_A[i] if pre_len_A[i] >= pre_len_B[i] else pre_dir_B[i]
        else:
            r0 = float(reference[0])
            r1 = float(reference[1])
            if r0 * r0 + r1 * r1 > 0:
                dA = abs(pre_dir_A[i, 0] * r0 + pre_dir_A[i, 1] * r1)
                dB = abs(pre_dir_B[i, 0] * r0 + pre_dir_B[i, 1] * r1)
                ax = pre_dir_A[i] if dA >= dB else pre_dir_B[i]
            else:
                ax = pre_dir_A[i] if pre_len_A[i] >= pre_len_B[i] else pre_dir_B[i]
        dot = ax[0] * reference[0] + ax[1] * reference[1]
        return ax if dot >= 0 else -ax

    # ── 4. 預計算邊緣截切遮罩（避免迴圈內重複計算 lengths[i] >= threshold）───────────
    if force_long_stable:
        frame_force_long_arr = lengths >= (
            config.EDGE_FRAME_LENGTH_RATIO * vehicle_length
        )  # (N,) bool
    else:
        frame_force_long_arr = np.zeros(num_frames, dtype=bool)

    # ── 5. 初始車頭建立（逃逸半徑掃描）──────────────────────────────────────────────
    init_idx = 0
    v_motion_init = np.array([0.0, 0.0])

    # 只掃前 10 幀當起點，避免 O(N²) 的全局掃描
    for i in range(min(10, num_frames)):
        dists = np.linalg.norm(smoothed_centers[i:] - smoothed_centers[i], axis=1)
        escape_indices = np.where(dists >= escape_radius)[0]
        if len(escape_indices) > 0:
            init_idx = i
            v_motion_init = (
                smoothed_centers[i + escape_indices[0]] - smoothed_centers[i]
            )
            break

    # 真的停很久都沒動，退回微小移動判斷
    if np.linalg.norm(v_motion_init) < 1e-9:
        for i in range(num_frames):
            if local_motion_norms[i] >= dynamic_min_move:
                init_idx = i
                v_motion_init = local_motions[i]
                break

    # ── 6. 設定初始幀車頭，並往前回補靜止幀 ──────────────────────────────────────────
    front_vectors[init_idx] = _align(init_idx, v_motion_init, force_long)
    for i in range(init_idx - 1, -1, -1):
        front_vectors[i] = _align(i, front_vectors[i + 1], force_long)

    # ── 7. 往後推導（前進 / 倒車 / 持續異常偵測 / 回溯修正）──────────────────────────
    last_forward_frame = init_idx
    cum_reverse_dist = 0.0
    anomaly_start_idx = None
    anomaly_motions = []

    for i in range(init_idx + 1, num_frames):
        prev_head = front_vectors[i - 1]
        v_motion = local_motions[i]
        ffl = bool(frame_force_long_arr[i])

        if local_motion_norms[i] >= dynamic_min_move:
            # prev_head 恆為單位向量，直接用 dot product 算 cos 角，省去 np.linalg.norm(prev_head)
            cos_a = (
                float(v_motion[0] * prev_head[0] + v_motion[1] * prev_head[1])
                / local_motion_norms[i]
            )
            angle_diff = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))

            if angle_diff <= max_turn_angle:
                # 【正常前進或順暢轉彎】
                anomaly_start_idx = None
                anomaly_motions = []
                front_vectors[i] = _align(i, v_motion, ffl)
                last_forward_frame = i
                cum_reverse_dist = 0.0

            elif angle_diff >= reverse_angle:
                # 【倒車中】
                anomaly_start_idx = None
                anomaly_motions = []
                front_vectors[i] = _align(i, prev_head, ffl)
                cum_reverse_dist += local_motion_norms[i]

                # 【防呆：累積倒車距離破表 → 假倒車，回溯翻轉】
                if cum_reverse_dist > max_reverse_dist:
                    start_flip = last_forward_frame + 1
                    front_vectors[start_flip : i + 1] = -front_vectors[
                        start_flip : i + 1
                    ]
                    last_forward_frame = i
                    cum_reverse_dist = 0.0

            else:
                # 【異常側滑 / 框格變形】(介於 MAX_TURN 與 REVERSE 之間)
                # 靜止不重設異常計數，允許累積跨越靜止期，以應對「移動稀疏」的誤判車
                if anomaly_start_idx is None:
                    anomaly_start_idx = i
                anomaly_motions.append(v_motion)

                reset_triggered = False
                if len(anomaly_motions) >= config.PERSISTENT_ANOMALY_THRESHOLD:
                    # 連續異常幀達門檻，計算位移一致性判斷是否為車頭誤判
                    all_m = np.array(anomaly_motions)
                    cumulative = np.sum(all_m, axis=0)
                    total_dist = float(np.sum(np.linalg.norm(all_m, axis=1)))
                    directionality = np.linalg.norm(cumulative) / (total_dist + 1e-9)

                    if directionality >= config.MOTION_DIRECTIONALITY_MIN:
                        # 車輛確實持續朝同一方向前進 → 車頭誤判，回溯修正
                        mean_motion = cumulative / np.linalg.norm(cumulative)
                        for j in range(anomaly_start_idx, i + 1):
                            ref = (
                                local_motions[j]
                                if local_motion_norms[j] >= dynamic_min_move
                                else mean_motion
                            )
                            front_vectors[j] = _align(
                                j, ref, bool(frame_force_long_arr[j])
                            )
                        last_forward_frame = i
                        cum_reverse_dist = 0.0
                        anomaly_start_idx = None
                        anomaly_motions = []
                        reset_triggered = True

                if not reset_triggered:
                    # 尚未達門檻，或位移不夠一致（真正的短暫側滑），信任上一幀慣性
                    front_vectors[i] = _align(i, prev_head, ffl)
        else:
            # 【靜止中】信任上一幀的車頭方向
            front_vectors[i] = _align(i, prev_head, ffl)

    # ── 8. 向量化角點重排（取代 O(N) Python for loop）────────────────────────────────
    # 影像座標系：x向右，y向下 → 車身左側法向量為 (fy, -fx)
    reordered_coords = np.empty_like(coords)
    v_left_all = np.column_stack([front_vectors[:, 1], -front_vectors[:, 0]])  # (N,2)
    proj_front_all = np.einsum("nki,ni->nk", coords, front_vectors)  # (N,4)

    sort_f = np.argsort(proj_front_all, axis=1)  # (N,4) 升序排列
    front_idx = sort_f[:, 2:]  # (N,2) 投影最大兩點（前方）
    back_idx = sort_f[:, :2]  # (N,2) 投影最小兩點（後方）

    front_corners = coords[_ni[:, None], front_idx]  # (N,2,2)
    back_corners = coords[_ni[:, None], back_idx]  # (N,2,2)

    # 前方兩點依左向量投影分 LF / RF
    proj_lf = np.einsum("nki,ni->nk", front_corners, v_left_all)  # (N,2)
    lf_local = np.argmax(proj_lf, axis=1)  # (N,) 左前在 front pair 中的局部 index
    rf_local = 1 - lf_local

    # 後方兩點依左向量投影分 LB / RB
    proj_lb = np.einsum("nki,ni->nk", back_corners, v_left_all)  # (N,2)
    lb_local = np.argmax(proj_lb, axis=1)  # (N,) 左後在 back pair 中的局部 index
    rb_local = 1 - lb_local

    reordered_coords[:, 0] = front_corners[_ni, lf_local]  # 左前 LF
    reordered_coords[:, 1] = front_corners[_ni, rf_local]  # 右前 RF
    reordered_coords[:, 2] = back_corners[_ni, rb_local]  # 右後 RB
    reordered_coords[:, 3] = back_corners[_ni, lb_local]  # 左後 LB

    # ── 9. 輸出格式化（向量化整數判斷，取代逐元素 is_integer()）──────────────────────
    flat = reordered_coords.flatten()
    rounded_int = np.round(flat).astype(np.int32)
    if np.all(np.abs(flat - rounded_int) < 1e-9):
        # 快速路徑：所有座標均為整數（絕大多數情況）
        flat_coords = rounded_int.tolist()
    else:
        flat_coords = [
            int(rounded_int[k])
            if abs(flat[k] - rounded_int[k]) < 1e-9
            else round(float(flat[k]), 2)
            for k in range(len(flat))
        ]
    return meta_info + [str(v) for v in flat_coords]


def process_trajectory_csv_file(input_csv, output_csv, on_progress=None):
    """主函數：讀取、處理並儲存軌跡檔（多行程平行版）"""
    t0 = time.perf_counter()
    logger.info("開始讀取資料...")
    config = TrajectoryConfig()

    with open(input_csv, "r", encoding="utf-8-sig") as f:
        lines = list(csv.reader(f))

    n_workers = max(1, (multiprocessing.cpu_count() or 2) - 1)
    # chunksize 控制每次傳給工作行程的任務數：太小 IPC 開銷大，太大進度條更新延遲
    chunk = max(1, min(200, len(lines) // max(1, n_workers * 4)))

    logger.info(
        f"共 {len(lines)} 台車，使用 {n_workers} 核心平行處理（每批 {chunk} 台）..."
    )

    with multiprocessing.Pool(
        processes=n_workers, initializer=_worker_init, initargs=(config,)
    ) as pool:
        results = []
        last_pct = -1
        for i, r in enumerate(
            tqdm(
                pool.imap(_process_row_worker, enumerate(lines), chunksize=chunk),
                total=len(lines),
                desc="處理進度",
                unit="台",
            ),
            1,
        ):
            results.append(r)
            if on_progress:
                pct = i * 100 // len(lines)
                if pct != last_pct:
                    on_progress(pct)
                    last_pct = pct

    processed_rows = [r for r in results if r is not None]

    logger.info("處理完成，正在匯出資料...")
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(processed_rows)

    elapsed = time.perf_counter() - t0
    mins, secs = divmod(elapsed, 60)
    time_str = f"{int(mins)} 分 {secs:.1f} 秒" if mins >= 1 else f"{elapsed:.2f} 秒"
    logger.info(f"成功儲存至 {output_csv}（總耗時：{time_str}）")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows 打包執行檔時必要
    parser = argparse.ArgumentParser(
        description="修正軌跡 bounding box 角點順序（依車輛移動方向重排為左前→右前→右後→左後）"
    )
    parser.add_argument("input", help="輸入軌跡 CSV 檔路徑")
    parser.add_argument(
        "-o",
        "--output",
        help="輸出 CSV 檔路徑（預設：在輸入檔名後加上 _fixed_{當下時間}，存於同一目錄）",
    )
    args = parser.parse_args()

    if args.output is None:
        p = Path(args.input)
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        args.output = str(p.parent / (p.stem + f"_fixed_{ts}" + p.suffix))

    process_trajectory_csv_file(args.input, args.output)
