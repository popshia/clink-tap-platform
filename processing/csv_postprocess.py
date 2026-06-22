import csv
import math

import numpy as np
from loguru import logger


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
    # 【機車強制長邊鎖定】
    # 這些車種的幾何形狀非常穩定 (不會有邊緣裁切問題)，強制以「物理長邊」作為車身軸線，絕對拒絕側向誤判
    FORCE_LONG_AXIS_TYPES = ["m"]

    # 針對不同車種給予不同的最大轉向限制，超過此角度視為框格變形的假位移 (側滑或斷軌前兆)
    MAX_TURN_ANGLE_MAP = {
        "b": 45.0,  # 大客車：轉向慢、框格大，嚴格限制防側滑與斷軌
        "t": 45.0,  # 大貨車：轉向慢、框格大，嚴格限制防側滑與斷軌
        "c": 90.0,  # 小客車：轉向適中，容忍 90 度校正
        "m": 120.0,  # 機車：配合臺灣待轉區急彎特性，放寬至 120 度。因已有 FORCE_LONG_AXIS 保護，不怕車頭標到側邊！
    }
    DEFAULT_MAX_TURN_ANGLE = 60.0  # 若遇到未知車種的預設值

    REVERSE_ANGLE_DEG = 120.0  # 連續追蹤時，與前一幀車頭夾角大於此度數才視為倒車

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
    # 邊緣使用常數填充，避免頭尾失真
    padded_centers = np.pad(centers, ((pad_width, pad_width), (0, 0)), mode="edge")
    smoothed = np.zeros_like(centers)
    for i in range(len(centers)):
        smoothed[i] = np.mean(padded_centers[i : i + window_size], axis=0)
    return smoothed


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

    # 如果是機車等穩定小物件，絕對相信物理長邊
    if force_long_axis:
        return dir_A if len_A > len_B else dir_B

    # 如果有參考向量 (且非強制長邊)，選擇與移動軌跡最平行的軸 (解決大車裁切問題)
    if reference_vector is not None and np.linalg.norm(reference_vector) > 0:
        # 選取與「參考向量」最平行的軸線 (解決邊緣裁切與機車側向鎖定問題)
        dot_A = abs(np.dot(dir_A, reference_vector))
        dot_B = abs(np.dot(dir_B, reference_vector))
        return dir_A if dot_A > dot_B else dir_B
    else:
        # 備案防呆：若完全無參考向量，才退回找長邊
        return dir_A if len_A > len_B else dir_B


def process_single_vehicle(row_data, config):
    """處理單台車的軌跡資料"""
    # 檢查是否為行人 (第 6 個欄位為車種)
    if len(row_data) >= 6 and row_data[5].strip().lower() == "p":
        # 行人直接回傳原資料，不進行角點重新排序
        return row_data

    meta_info = row_data[:6]
    v_type = meta_info[5].strip().lower()

    # 判斷該車種是否需要強制長邊鎖定與對應的各項物理限制
    force_long = v_type in config.FORCE_LONG_AXIS_TYPES
    max_turn_angle = config.MAX_TURN_ANGLE_MAP.get(
        v_type, config.DEFAULT_MAX_TURN_ANGLE
    )
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

    # 抽樣計算該車的實體長度。為兼顧效能與穩定性，取所有幀計算長邊並取中位數
    lengths = []
    for pts in coords:
        v01 = np.linalg.norm(pts[1] - pts[0])
        v12 = np.linalg.norm(pts[2] - pts[1])
        lengths.append(max(v01, v12))
    vehicle_length = np.median(lengths) if lengths else 10.0

    # 計算這台車專屬的動態閾值 (加上保底數值避免浮點數微小雜訊)
    dynamic_min_move = max(
        config.ABSOLUTE_MIN_MOVE_PX, vehicle_length * config.MIN_MOVE_RATIO
    )
    escape_radius = max(config.ABSOLUTE_ESCAPE_PX, vehicle_length * config.ESCAPE_RATIO)
    max_reverse_dist = vehicle_length * max_reverse_ratio  # 最大倒車距離極限

    local_motions = np.zeros((num_frames, 2))
    for i in range(num_frames):
        target_idx = min(i + config.LOOKAHEAD_FRAMES, num_frames - 1)
        local_motions[i] = smoothed_centers[target_idx] - smoothed_centers[i]

    front_vectors = np.zeros((num_frames, 2))

    # --- 【修復：效能優化版未來掃描法 (Vectorization)】 ---
    init_idx = 0
    v_motion_init = np.array([0.0, 0.0])

    # 只要取前 10 幀當作可能的起點來驗證即可，避免 O(N^2) 的悲劇
    for i in range(min(10, num_frames)):
        # 利用 numpy 向量化，瞬間算出第 i 幀與未來所有幀的距離
        dists = np.linalg.norm(smoothed_centers[i:] - smoothed_centers[i], axis=1)
        # 找出大於逃逸半徑的索引
        escape_indices = np.where(dists >= escape_radius)[0]

        if len(escape_indices) > 0:
            init_idx = i
            target_j = i + escape_indices[0]  # 還原成原始的絕對 index
            v_motion_init = (
                smoothed_centers[target_j] - smoothed_centers[i]
            )  # 絕對朝前的向量
            break

    # 如果真的停了幾萬幀都沒動，退回微小移動判斷
    if np.linalg.norm(v_motion_init) == 0:
        for i in range(num_frames):
            if np.linalg.norm(local_motions[i]) >= dynamic_min_move:
                init_idx = i
                v_motion_init = local_motions[i]
                break
    # -----------------------------------------------------

    # 確立初始車頭 (傳入 force_long 參數)
    geom_axis_init = get_vehicle_axis(
        coords[init_idx],
        centers[init_idx],
        reference_vector=v_motion_init,
        force_long_axis=force_long,
    )
    if np.linalg.norm(v_motion_init) > 0:
        if np.dot(geom_axis_init, v_motion_init) < 0:
            front_vectors[init_idx] = -geom_axis_init
        else:
            front_vectors[init_idx] = geom_axis_init
    else:
        front_vectors[init_idx] = geom_axis_init

    # 往前推導回補 (將起步前漫長的停等幀，全部填上這組正確的車頭方向)
    for i in range(init_idx - 1, -1, -1):
        prev_head_back = front_vectors[i + 1]
        geom_axis = get_vehicle_axis(
            coords[i],
            centers[i],
            reference_vector=prev_head_back,
            force_long_axis=force_long,
        )
        if np.dot(geom_axis, prev_head_back) < 0:
            front_vectors[i] = -geom_axis
        else:
            front_vectors[i] = geom_axis

    # --- 【新增：回溯翻轉狀態追蹤器】 ---
    last_forward_frame = -1  # 記錄最後一次正常前進的幀索引
    cum_reverse_dist = 0.0  # 累積倒車距離

    # 往後推導 (自我校正與物理慣性保護機制)
    for i in range(init_idx + 1, num_frames):
        prev_head = front_vectors[i - 1]
        v_motion = local_motions[i]

        if np.linalg.norm(v_motion) >= dynamic_min_move:
            angle_diff = calculate_angle(v_motion, prev_head)

            if angle_diff <= max_turn_angle:
                # 【正常前進或順暢轉彎】
                geom_axis = get_vehicle_axis(
                    coords[i],
                    centers[i],
                    reference_vector=v_motion,
                    force_long_axis=force_long,
                )
                if np.dot(geom_axis, v_motion) < 0:
                    front_vectors[i] = -geom_axis
                else:
                    front_vectors[i] = geom_axis

                # 記錄正常前進的時刻，並將倒車計數器歸零
                last_forward_frame = i
                cum_reverse_dist = 0.0

            elif angle_diff >= config.REVERSE_ANGLE_DEG:
                # 【倒車中】
                geom_axis = get_vehicle_axis(
                    coords[i],
                    centers[i],
                    reference_vector=prev_head,
                    force_long_axis=force_long,
                )
                if np.dot(geom_axis, prev_head) < 0:
                    front_vectors[i] = -geom_axis
                else:
                    front_vectors[i] = geom_axis

                # 累加倒車距離
                cum_reverse_dist += np.linalg.norm(v_motion)

                # 【防呆機制：累積倒車距離檢驗與回溯翻轉】
                if cum_reverse_dist > max_reverse_dist:
                    # 倒車距離破表！判定為假倒車(車頭被鎖死在後方)。
                    # 啟動回溯機制：從上次正常前進的下一幀開始，一路把車頭 180 度翻轉回來！
                    start_flip = max(0, last_forward_frame + 1)
                    for k in range(start_flip, i + 1):
                        front_vectors[k] = -front_vectors[k]

                    # 翻轉完畢後，目前這幀在物理上已變成「正常前進」
                    last_forward_frame = i
                    cum_reverse_dist = 0.0

            else:
                # 【異常側滑 / 框格變形】 (介於 MAX_TURN 與 REVERSE 之間)
                # 無視假性位移，強制信任上一幀的車頭慣性
                geom_axis = get_vehicle_axis(
                    coords[i],
                    centers[i],
                    reference_vector=prev_head,
                    force_long_axis=force_long,
                )
                if np.dot(geom_axis, prev_head) < 0:
                    front_vectors[i] = -geom_axis
                else:
                    front_vectors[i] = geom_axis

                # 異常側滑不計入倒車距離，也不更新前進幀
        else:
            # 【靜止中】
            # 車輛沒動，信任上一幀的車頭方向
            geom_axis = get_vehicle_axis(
                coords[i],
                centers[i],
                reference_vector=prev_head,
                force_long_axis=force_long,
            )
            if np.dot(geom_axis, prev_head) < 0:
                front_vectors[i] = -geom_axis
            else:
                front_vectors[i] = geom_axis

    # 5. 根據車頭向量，重新排序 4 個角點
    reordered_coords = np.zeros_like(coords)
    for i in range(num_frames):
        pts = coords[i]
        v_front = front_vectors[i]

        # 影像座標系：x向右，y向下 -> 車身左側法向量：(dy, -dx)
        v_left = np.array([v_front[1], -v_front[0]])

        # 將 4 個點投影到車頭向量上
        proj_front = np.dot(pts, v_front)
        front_indices = np.argsort(proj_front)[-2:]
        back_indices = np.argsort(proj_front)[:2]

        front_pts = pts[front_indices]
        back_pts = pts[back_indices]

        # 將車頭的兩個點投影到左側法向量上
        proj_left_front = np.dot(front_pts, v_left)
        lf_idx = np.argmax(proj_left_front)
        rf_idx = np.argmin(proj_left_front)

        # 同理處理車尾
        proj_left_back = np.dot(back_pts, v_left)
        lb_idx = np.argmax(proj_left_back)
        rb_idx = np.argmin(proj_left_back)

        # 依序存入：左前 (LF), 右前 (RF), 右後 (RB), 左後 (LB)
        reordered_coords[i, 0] = front_pts[lf_idx]
        reordered_coords[i, 1] = front_pts[rf_idx]
        reordered_coords[i, 2] = back_pts[rb_idx]
        reordered_coords[i, 3] = back_pts[lb_idx]

    # 為了保持原先資料格式，若原座標為整數則轉換為 int，否則保留小數
    flat_coords = [
        int(v) if v.is_integer() else round(v, 2) for v in reordered_coords.flatten()
    ]
    return meta_info + [str(v) for v in flat_coords]


def process_trajectory_csv_file(input_csv, output_csv):
    """主函數：讀取、處理並儲存軌跡檔"""
    logger.info("開始讀取資料...")
    config = TrajectoryConfig()
    processed_rows = []

    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        lines = list(reader)

    for index, row in enumerate(lines):
        try:
            row = [item for item in row if item.strip() != ""]
            if len(row) < 6:
                continue
            new_row = process_single_vehicle(row, config)
            processed_rows.append(new_row)
        except Exception as e:
            logger.warning(f"處理第 {index} 筆資料 (ID: {row[0]}) 時發生錯誤: {e}")

    logger.info("處理完成，正在匯出資料...")
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(processed_rows)
    logger.info(f"成功儲存至 {output_csv}")


if __name__ == "__main__":
    try:
        from logging_config import setup_logging

        setup_logging()
    except ImportError:
        # Run by file path without the repo root on sys.path; Loguru defaults apply.
        pass

    INPUT_FILE = "raw_trajectory.csv"
    OUTPUT_FILE = "fixed_trajectory.csv"
    process_trajectory_csv_file(INPUT_FILE, OUTPUT_FILE)
