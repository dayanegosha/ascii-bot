# devz.py
import os
import cv2
import numpy as np
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
    ReplyKeyboardRemove,
)
from aiogram.filters import Command
from aiogram.enums import ContentType
from moviepy.editor import ImageSequenceClip
import asyncio
from concurrent.futures import ProcessPoolExecutor, as_completed
from aiogram.client.bot import DefaultBotProperties
from PIL import Image, ImageDraw, ImageFont
import tempfile
import time
import multiprocessing

# === Конфигурация ===
API_TOKEN = os.getenv("BOT_TOKEN", "")
if not API_TOKEN:
    raise SystemExit(
        "BOT_TOKEN is not set. Export it first, e.g. `export BOT_TOKEN=123:ABC` "
        "(see README)."
    )
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# === Настройки ASCII / шрифт ===
# Расширенный набор символов для лучшего градиента и качества, как на примерах
ASCII_CHARS = r" .:+-*#%"

# Попытка найти моноширинный шрифт (macOS / Linux common paths). Если не найден — fallback.
FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/Library/Fonts/Courier New Bold.ttf",
    "/Library/Fonts/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]
FONT_PATH = None
for p in FONT_PATHS:
    if os.path.exists(p):
        FONT_PATH = p
        print(f"[INFO] Loaded font path: {p}")
        break
if FONT_PATH is None:
    print("[WARN] System mono font not found — using default PIL font. Install a mono TTF for better visuals.")

# Размеры шрифта для разных настроек и качеств (для ультра уменьшили размер шрифта для ускорения, но сохранили качество)
FONT_SIZES_ORDINARY = {"маленький": 48, "средний": 24, "большой": 12}
FONT_SIZES_ULTRA = {"маленький": 16, "средний": 10, "большой": 6}

# Параметры производительности
MAX_WORKERS = os.cpu_count() or 4  # Используем количество ядер CPU

# Состояния пользователей
user_settings = {}
user_stop_events = {}

# === Вспомогательные функции ===
def map_gray_to_char(gray_value: int) -> str:
    idx = gray_value * (len(ASCII_CHARS) - 1) // 255
    return ASCII_CHARS[idx]

def load_font(size: int):
    if FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()

def get_font_metrics(font: ImageFont.FreeTypeFont):
    char_w = int(font.getlength("M"))
    bbox = font.getbbox("M")
    char_h = bbox[3] - bbox[1]
    return char_w, char_h

def frame_to_ascii_image_pil(frame, size="medium", colored=False, quality="обычное", stop_event=None):
    font_sizes = FONT_SIZES_ULTRA if quality == "ультра" else FONT_SIZES_ORDINARY
    font_size = font_sizes.get(size, 24)
    font = load_font(font_size)
    char_w, char_h = get_font_metrics(font)

    orig_h, orig_w, _ = frame.shape
    aspect = orig_w / orig_h

    if quality == "ультра":
        if orig_h > orig_w:
            TARGET_W, TARGET_H = 2160, 3840
        else:
            TARGET_W, TARGET_H = 3840, 2160
    else:
        if orig_h > orig_w:
            TARGET_W, TARGET_H = 1080, 1920
        else:
            TARGET_W, TARGET_H = 1920, 1080

    num_cols_max = TARGET_W // char_w
    num_rows_max = TARGET_H // char_h

    num_cols = min(num_cols_max, int(num_rows_max * aspect))
    num_rows = max(1, int(num_cols / aspect))

    frame_resized = cv2.resize(frame, (num_cols, num_rows))

    img_pil = Image.new("RGB", (TARGET_W, TARGET_H), (0, 0, 0))
    draw = ImageDraw.Draw(img_pil)

    draw_w = num_cols * char_w
    draw_h = num_rows * char_h
    offset_x = (TARGET_W - draw_w) // 2
    offset_y = (TARGET_H - draw_h) // 2

    for y in range(num_rows):
        if stop_event and stop_event.is_set():
            raise ValueError("Processing stopped")
        for x in range(num_cols):
            b, g, r = frame_resized[y, x]
            gray = int(0.3 * r + 0.59 * g + 0.11 * b)
            char = map_gray_to_char(gray)
            if colored:
                color = (r, g, b)  # RGB for PIL: red, green, blue
            else:
                color = (gray, gray, gray)
            draw.text(
                (offset_x + x * char_w, offset_y + y * char_h),
                char,
                font=font,
                fill=color
            )

    return np.array(img_pil)

# Worker function for processing individual frames
def worker(i_frame, temp_dir, size, colored, quality, stop_event):
    try:
        input_file = f"{temp_dir}/input_frame_{i_frame:05d}.jpg"
        frame = cv2.imread(input_file)
        if frame is None:
            raise RuntimeError(f"Failed to read frame {i_frame} from {input_file}")
        out = frame_to_ascii_image_pil(frame, size=size, colored=colored, quality=quality, stop_event=stop_event)
        frame_file = f"{temp_dir}/ascii_frame_{i_frame:05d}.jpg"
        cv2.imwrite(frame_file, cv2.cvtColor(out, cv2.COLOR_RGB2BGR))
        return i_frame
    except Exception as ex:
        return i_frame, ex

def format_eta(seconds):
    if seconds < 0:
        return "00:00"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

# === Обработка видео с прогрессом, логами и многопоточностью ===
async def process_video_progress(file_path: str, size: str, colored: bool, quality: str, message: Message):
    user_id = message.from_user.id
    manager = multiprocessing.Manager()
    stop_event = manager.Event()
    user_stop_events[user_id] = stop_event

    try:
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            raise RuntimeError("Не удалось открыть видео файл для чтения.")

        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        fps = src_fps if src_fps <= 60 else 60.0

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            # Fallback count
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            total_frames = 0
            while True:
                ret, _ = cap.read()
                if not ret:
                    break
                total_frames += 1
            cap.release()
            cap = cv2.VideoCapture(file_path)  # Reopen

        # Check duration
        duration_sec = total_frames / fps
        if duration_sec > 180:
            cap.release()
            raise ValueError("Видео слишком длинное (макс 3 минуты).")

        print(f"[INFO] Кадров: {total_frames}, FPS: {src_fps}, используемый FPS: {fps}")

        if total_frames == 0:
            cap.release()
            raise ValueError("Видео пустое.")

        progress_msg = await message.answer("Извлечение кадров: 0% (Примерное время ожидания: --:--)")

        out_path = f"ascii_{message.from_user.id}_{int(asyncio.get_event_loop().time())}.mp4"

        with tempfile.TemporaryDirectory() as temp_dir:
            # Pre-extract all frames to temp jpgs
            start_extract = time.time()
            for i in range(total_frames):
                if stop_event.is_set():
                    raise ValueError("Processing stopped")
                ret, frame = cap.read()
                if not ret:
                    raise RuntimeError(f"Failed to read frame {i}")
                input_file = f"{temp_dir}/input_frame_{i:05d}.jpg"
                cv2.imwrite(input_file, frame)
                percent = int((i + 1) / total_frames * 100)
                time_so_far = time.time() - start_extract
                if i + 1 > 0:
                    avg_time = time_so_far / (i + 1)
                    eta = avg_time * (total_frames - i - 1)
                else:
                    eta = 0
                print(f"[INFO] Извлечен кадр {i+1}/{total_frames} ({percent}%)")
                if i % 10 == 0:  # Update less frequently
                    try:
                        await bot.edit_message_text(
                            text=f"Извлечение кадров: {percent}% (Примерное время ожидания: {format_eta(eta)})",
                            chat_id=message.chat.id,
                            message_id=progress_msg.message_id,
                        )
                    except Exception:
                        pass
            cap.release()

            await bot.edit_message_text(
                text="Обработка: 0% (Примерное время ожидания: --:--)",
                chat_id=message.chat.id,
                message_id=progress_msg.message_id,
            )

            start_process = time.time()
            with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [executor.submit(worker, i, temp_dir, size, colored, quality, stop_event) for i in range(total_frames)]
                completed = 0
                last_percent = -1
                for fut in as_completed(futures):
                    result = fut.result()
                    if isinstance(result, tuple) and isinstance(result[1], Exception):
                        print(f"[ERROR] Ошибка при обработке кадра {result[0]}: {result[1]}")
                        raise result[1]
                    completed += 1
                    percent = int(completed / total_frames * 100)
                    time_so_far = time.time() - start_process
                    avg_time = time_so_far / completed
                    eta = avg_time * (total_frames - completed)
                    print(f"[INFO] Обработан кадр {result+1}/{total_frames} ({percent}%)")
                    if percent != last_percent:
                        last_percent = percent
                        try:
                            await bot.edit_message_text(
                                text=f"Обработка: {percent}% (Примерное время ожидания: {format_eta(eta)})",
                                chat_id=message.chat.id,
                                message_id=progress_msg.message_id,
                            )
                        except Exception:
                            pass

            # Build video from temp frames
            print("[INFO] Все кадры обработаны. Начинаю сборку видео...")
            frame_files = [f"{temp_dir}/ascii_frame_{i:05d}.jpg" for i in range(total_frames)]
            clip = ImageSequenceClip(frame_files, fps=fps)
            clip.write_videofile(out_path, codec="libx264", audio=False, threads=MAX_WORKERS, bitrate="8000k", verbose=False, logger=None)
            print(f"[INFO] Видео сохранено: {out_path}")

        # Delete progress
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=progress_msg.message_id)
        except Exception:
            pass

        return out_path
    except ValueError as e:
        if str(e) == "Processing stopped":
            await message.answer("Обработка прервана.")
            return None
        else:
            raise e
    finally:
        if user_id in user_stop_events:
            del user_stop_events[user_id]

# === Хэндлеры ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Маленький"), KeyboardButton(text="Средний"), KeyboardButton(text="Большой")]],
        resize_keyboard=True,
    )
    await message.answer("Привет! Выбери размер ASCII видео (маленький - меньше деталей, быстрее; большой - больше деталей, медленнее):", reply_markup=kb)

@dp.message(F.text.in_(["Маленький", "Средний", "Большой"]))
async def choose_size(message: Message):
    user_settings[message.from_user.id] = {"size": message.text.lower(), "colored": None, "quality": None}
    kb_mode = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Цветной"), KeyboardButton(text="Монохром")]],
        resize_keyboard=True,
    )
    await message.answer("Теперь выбери режим:", reply_markup=kb_mode)

@dp.message(F.text.in_(["Цветной", "Монохром"]))
async def choose_mode(message: Message):
    settings = user_settings.get(message.from_user.id, {})
    settings["colored"] = message.text == "Цветной"
    user_settings[message.from_user.id] = settings
    kb_quality = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Обычное"), KeyboardButton(text="Ультра")]],
        resize_keyboard=True,
    )
    await message.answer("Теперь выбери качество (Ультра - выше разрешение, медленнее):", reply_markup=kb_quality)

@dp.message(F.text.in_(["Обычное", "Ультра"]))
async def choose_quality(message: Message):
    settings = user_settings.get(message.from_user.id, {})
    settings["quality"] = message.text.lower()
    user_settings[message.from_user.id] = settings
    await message.answer("Отправь мне видео до 3 минут (файл или обычное видео):", reply_markup=ReplyKeyboardRemove())

@dp.message(F.content_type.in_([ContentType.VIDEO, ContentType.DOCUMENT]))
async def handle_video(message: Message):
    user_id = message.from_user.id
    if user_id not in user_settings or user_settings[user_id]["colored"] is None or user_settings[user_id]["quality"] is None:
        await message.answer("Сначала выбери размер, режим и качество!")
        return

    file_path = f"{user_id}_in.mp4"
    out_path = None
    try:
        if message.content_type == ContentType.VIDEO and message.video:
            file = await bot.get_file(message.video.file_id)
        elif message.content_type == ContentType.DOCUMENT and message.document:
            file = await bot.get_file(message.document.file_id)
        else:
            await message.answer("Неподдерживаемый формат.")
            return

        await bot.download_file(file.file_path, file_path)
        print(f"[INFO] Файл загружен: {file_path}")

        out_path = await process_video_progress(
            file_path, user_settings[user_id]["size"], user_settings[user_id]["colored"], user_settings[user_id]["quality"], message
        )

        if out_path:
            await message.answer_document(FSInputFile(out_path, filename="ascii_video_devz.mp4"), caption="Вот твоё ASCII-видео 🎬")

        kb_restart = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Снова начать")]], resize_keyboard=True)
        await message.answer("Преобразуем что-то ещё?", reply_markup=kb_restart)

        user_settings.pop(user_id, None)

    except Exception as e:
        print(f"[ERROR] {e}")
        await message.answer(f"Ошибка: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        if out_path and os.path.exists(out_path):
            os.remove(out_path)

@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    if user_id in user_stop_events:
        user_stop_events[user_id].set()
        await message.answer("Прерывание обработки...")
    else:
        await message.answer("Нет активной обработки для прерывания.")

@dp.message(F.text == "Снова начать")
async def restart_quick(message: Message):
    await cmd_start(message)

# === Запуск ===
async def main():
    print("[INFO] Бот запущен и ждёт сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())