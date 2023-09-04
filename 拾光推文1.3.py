import asyncio
import base64
import concurrent.futures
import hashlib
import html
import json
import os
import random
import re
import sys
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from threading import Timer

import aiofiles
import azure.cognitiveservices.speech as speechsdk
import edge_tts
import librosa
import openai
import requests
import soundfile as sf
from azure.cognitiveservices.speech import (AudioDataStream, ResultReason,
                                            SpeechConfig, SpeechSynthesizer)
from docx import Document
from edge_tts import exceptions
from flask import (Flask, abort, jsonify, make_response, request, send_file,
                   send_from_directory)
from pydub import AudioSegment
from tqdm import tqdm
from tqdm.asyncio import tqdm as async_tqdm


def get_http_time():
    response = requests.head("https://www.baidu.com")
    date = response.headers["date"]
    return datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z")


def check_expiration():
    expiration_time = datetime(2023, 9, 20)
    current_time = get_http_time()
    if current_time > expiration_time:
        print("程序已过期，请联系供应商。")
        exit()


check_expiration()


def get_unique_folder_name(base_folder):
    # 添加时间戳来获取唯一的文件夹名
    timestamp = int(time.time())
    folder_name = f"{base_folder}_{timestamp}"
    return folder_name


BASE_DIR = "C:\\do_video"
IMAGE_DIR = os.path.join(BASE_DIR, "image")
VOICE_DIR = os.path.join(BASE_DIR, "voice")
VOICE2_DIR = os.path.join(BASE_DIR, "voice2")

# 使用 `get_unique_folder_name` 函数创建并获取新的文件夹路径

new_image_dir = get_unique_folder_name(IMAGE_DIR)
new_voice_dir = get_unique_folder_name(VOICE_DIR)
new_voice2_dir = get_unique_folder_name(VOICE2_DIR)


if getattr(sys, "frozen", False):
    # If the application is running as a bundle
    ffmpeg_path = os.path.join(sys._MEIPASS, "ffmpeg-win64-v4.2.2.exe")
else:
    # If the application is running as a script (e.g., during development)
    ffmpeg_path = "D:/txt_to_video/env/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win64-v4.2.2.exe"


def get_project_path():
    # 获取当前文件所在的绝对路径
    current_file_path = os.path.abspath(__file__)
    # 获取当前文件所在的目录路径
    current_directory = os.path.dirname(current_file_path)
    # 获取项目路径（上一级目录）
    project_path = os.path.dirname(current_directory)
    # 规范化路径，使其在Windows环境下可识别
    project_path = os.path.normpath(project_path)
    return project_path


api_key = ""
results = {}
formatted_data_global = []
audio_list_global = []
paint_url = ""
result_out_list = []
# project_path = get_project_path()
# print("项目路径:", project_path)


def file_if_not_exists(file_path):
    if not os.path.exists(file_path):
        # 获取文件所在目录
        directory = os.path.dirname(file_path)
        # 创建目录（包括所有需要的父目录）
        os.makedirs(directory, exist_ok=True)
        # 创建空文件
        with open(file_path, "w") as file:
            pass
        return make_response(f"文件 '{file_path}' 创建成功！")
    else:
        return make_response(f"文件 '{file_path}' 已存在。")


def read_json_file(file_path):
    try:
        with open(file_path, "r") as file:
            data = json.load(file)
        return data
    except IOError as e:
        print(f"读取文件时出现错误：{e}")
        return None


def write_json_file(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        print(f"成功写入JSON文件：{file_path}")
        return f"成功写入JSON文件：{file_path}"
    except IOError as e:
        print(f"写入文件时出现错误：{e}")


# 读取a.json文件的内容
def save_json_file(to_data, file_path):
    data = read_json_file(file_path)
    if data:
        # 打印读取到的数据
        print(data)

        # 修改数据
        # to_data = {"openai_wkey":"sdkfjiutr@#"}
        data.update(to_data)
        print(data)
        # 写入更新后的数据到a.json文件
        return write_json_file(file_path, data)
    else:
        return write_json_file(file_path, to_data)


# read_json_file('C:\\Users\\86185\\Desktop\\work\\to_videos\\to_video\\common_util\\data_config.json')

SETTINGS = {"audio_subscription": "", "audio_region": "", "audio_voice_name": ""}


# 定义Edge TTS的版本号
EDGE_TTS_VERSION = "6.1.5"

# 定义支持的语言和对应的语音模型
# 具体支持的中文声音列表如下：
# zh-CN-XiaoxiaoNeural、zh-CN-XiaoyiNeural、zh-CN-YunjianNeural
# zh-CN-YunxiNeural、zh-CN-YunxiaNeural、zh-CN-YunyangNeural
# zh-HK-HiuGaaiNeural、zh-HK-HiuMaanNeural、zh-HK-WanLungNeural
# zh-TW-HsiaoChenNeural、zh-TW-YunJheNeural、zh-TW-HsiaoYuNeural
SUPPORTED_VOICES = {
    "zh-CN": "zh-CN-XiaoxiaoNeural",
    "en-US": "JennyNeural",
}


class FreeSpeechProvider:
    def __init__(self, config=None):
        self._config = config or {}

    # 返回支持的语言
    @property
    def supported_languages(self):
        return list(SUPPORTED_VOICES.keys())

    # 使用edge_tts库获取语音数据
    async def get_tts_audio(self, message, language):
        return await self._async_get_tts_audio(message, language)

    async def _async_get_tts_audio(self, message, language):
        mp3 = b""
        service_data = language

        tts = edge_tts.Communicate(message, **service_data)
        try:
            async for chunk in tts.stream():
                if chunk["type"] == "audio":
                    mp3 += chunk["data"]
        except exceptions.NoAudioReceived:
            return None, None

        return "mp3", mp3


class SpeechProvider:
    def __init__(self, config=None):
        self._config = config or {}

    # 异步获取语音合成结果
    async def get_tts_audio(self, message, language, index):
        while True:  # 无限循环进行尝试
            try:
                # 创建语音合成配置对象
                speech_config = SpeechConfig(
                    subscription=SETTINGS["audio_subscription"],
                    region=SETTINGS["audio_region"],
                )
                speech_config.speech_synthesis_voice_name = SETTINGS["audio_voice_name"]

                # 创建语音合成器
                synthesizer = SpeechSynthesizer(
                    speech_config=speech_config, audio_config=None
                )

                # 将要合成语音的文本转义以便能够正确地在SSML中使用
                escaped_message = html.escape(message)

                # 构造SSML文本
                ssml_text = f"""
                <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='{language}'>
                  <voice name='{SETTINGS["audio_voice_name"]}'>
                    <mstts:express-as style='{SETTINGS["audio_style"]}' role='{SETTINGS["audio_role"]}' styledegree='{SETTINGS["audio_style_degree"]}'>
                      <prosody rate='{SETTINGS["audio_prosody_rate"]}' pitch='{SETTINGS["audio_prosody_pitch"]}' volume='{SETTINGS["audio_prosody_volume"]}'>
                        {escaped_message}
                      </prosody>
                    </mstts:express-as>
                  </voice>
                </speak>
                """

                # 异步进行语音合成
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, lambda: synthesizer.speak_ssml_async(ssml_text).get()
                )

                # 判断语音合成是否成功，成功则返回音频数据，否则打印错误信息并继续下一轮尝试
                if result.reason == ResultReason.SynthesizingAudioCompleted:
                    audio_data = BytesIO(result.audio_data)
                    return {"index": index, "audio_data": audio_data, "error": None}
                elif result.reason == ResultReason.Canceled:
                    cancellation_details = speechsdk.SpeechSynthesisCancellationDetails(
                        result
                    )
                    print(
                        f"序号 {index} 的语音合成出错，错误信息：{str(cancellation_details.reason)} {str(cancellation_details.error_details)}，正在进行下一次尝试..."
                    )
            except Exception as e:
                print(f"序号 {index} 的语音合成出错，错误信息：{str(e)}，正在进行下一次尝试...")


def merge_short_sentences(sentences, min_length):
    # 定义一个函数，将字符数少于设定值的句子进行合并
    merged_sentences = []
    buffer_sentence = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if len(buffer_sentence + sentence) < min_length:
            buffer_sentence += " " + sentence if buffer_sentence else sentence
        else:
            if buffer_sentence:
                merged_sentences.append(buffer_sentence)
            buffer_sentence = sentence

    if buffer_sentence:
        merged_sentences.append(buffer_sentence)

    return merged_sentences


def chat_completion(messages, max_tokens, api_key):
    url = "https://chat.huby.cloud/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}" # 使用传入的授权令牌
    }
    payload = {
        "model": "gpt-3.5-turbo-16k",
        "messages": messages,
        "max_tokens": max_tokens,
        "n": 1,
        "stop": None
    }

    response = requests.post(url, json=payload, headers=headers)

    # 检查HTTP响应的状态码
    if response.status_code != 200:
        raise Exception("请求失败，状态码：" + str(response.status_code))

    response_content = response.json()

    return response_content["choices"][0]["message"]["content"].strip()

def request_with_retry(messages, max_tokens=500, max_requests=90, cooldown_seconds=60, max_timeout_errors=5):
    timeout_errors = 0 # 超时错误计数器

    while True:
        try:
            make_response = chat_completion(messages, max_tokens, api_key)
            # 返回 API 返回的内容，同时去除两端的空格
            return make_response.strip()
        
        
        
        
        except requests.exceptions.RequestException as e:
            if "Bad Gateway" in str(e) or e.response.status_code == 502:
                # 对 "Bad Gateway" 错误进行特别处理
                print("Bad Gateway 错误，服务器可能暂时不可用。稍后重试。")
                time.sleep(5) # 等待一段时间后重试
            else:
                # 对其他 HTTP 错误进行处理
                print(f"发生 HTTP 错误：{e}")
                sys.exit(1) # 退出程序，返回错误代码 1
        except Exception as e:
            print(f"发生未知错误：{e}")
            sys.exit(1) # 退出程序，返回错误代码 1

def translate_to_english(text):
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant.This is very important if you encounter text such as <lora:add detail:1> and just skip it and keep this field!",
        },
        {
            "role": "user",
            "content": f'Translate the following text to English: "{text}". Ensure the translation is fluent and semantically similar, rather than being a direct translation. You can infer and supplement missing or implicit information from the sentence\'s context, but do not overdo it. Apart from the translated result, do not include any irrelevant content or explanations in your make_response.This is very important if you encounter text such as <lora:add detail:1> and just skip it and keep this field!',
        },
    ]
    return request_with_retry(messages)

def translate(text, from_lang, to_lang):
    # 定义两组 appid 和 secretKey
    group1 = {
        "appid": "20230804001769054",  # 你的第一组appid
        "secretKey": "3p9GV2XEkHKkl3vGeV48",  # 你的第一组secretKey
    }

    group2 = {
        "appid": "20230819001786603",  # 你的第二组appid
        "secretKey": "bEgCPs9MiXQHmqy9Cov8",  # 你的第二组secretKey
    }

    # 随机选择其中一组
    selected_group = random.choice([group1, group2])

    appid = selected_group["appid"]
    secretKey = selected_group["secretKey"]
    salt = "1234567890"
    sign = hashlib.md5((appid + text + salt + secretKey).encode("utf-8")).hexdigest()
    url = "http://api.fanyi.baidu.com/api/trans/vip/translate"
    params = {
        "q": text,
        "from": from_lang,
        "to": to_lang,
        "appid": appid,
        "salt": salt,
        "sign": sign,
    }
    response = requests.get(url, params=params)
    result = json.loads(response.text)

    # 翻译失败重新请求
    if "error_code" in result:
        return translate(text, from_lang, to_lang)

    translated_text = result["trans_result"][0]["dst"]
    return translated_text


def do_prompt(text):
    text = translate(text, "zh", "en")

    messages = [
        {
            "role": "system",
            "content": "Assistant, your task is to convert novel text into specific prompts, considering the novel's background, following detailed rules and examples.",
        },
        {
            "role": "user",
            "content": f"Conversion Rules: Your prompt must directly reflect the novel's text without digression. The rules include: \
    (1) Extract directly from the text key elements such as main characters (if present), essential actions, significant items, and core emotions, \
    (2) Emphasize visual elements such as shape, color, texture, and their interaction, \
    (3) Define the composition by providing cues for characters (if present), background, foreground, etc., \
    (4) Limit the prompt to no more than 15 tags or 30 words to ensure conciseness, \
    (5) Focus on portraying the visual and emotional aspect with a few vivid adjectives, \
    (6) Include tags like '1girl', '2boys' to indicate the number and gender of human characters, but only if human characters are present in the scene, \
    (7) Avoid abstract or ambiguous terms that may lead to confusion, \
    (8) Avoid excessive details and focus on essential elements that convey the scene or emotion",
        },
        {
            "role": "user",
            "content": "Prompt Format Requirements: The prompt must contain parts about the subject, material, additional details, image quality, artistic style, color tone, lighting, etc., without splitting or using symbols like ':' or '.'. Specific requirements include: \
    - Subject: Detailed English description like 'A girl in a garden' with relevant details, \
    - For human subjects, use tags like '1girl' for one girl, '2girls' for two girls, or '1boy' for one boy to specify the gender and number, \
    - Material: The type of art, like illustrations, oil painting, 3D rendering, and photography, \
    - Additional Details: Optional details for a harmonious image, \
    - Limitations: Tags in English words or phrases, no sentences, explanation, max 40 tags, 60 words, no quotes, use ',' as a delimiter, ordered by importance.",
        },
        {
            "role": "user",
            "content": f"Example conversions: \
    'The girl sat on the sofa' -> '1girl, sitting on a cozy couch, crossing legs, soft light', \
    'Beauty in the street' -> 'polaroid photo, night photo, photo of 24 y.o beautiful woman, pale skin, bokeh, motion blur', \
    'Children swing happily at the foot of the Albers mountain' -> '(a big swing:1.2), sundress, straw hat, (long blonde hair, brown eyes:1.5), eyes in highlight, catch light eyes, specular highlight eyes, 1girl, (child:1.1), sitting, in the sky, mountain alps, happy', \
    'The little girl crouched' -> '1 girl, whole body, from_side, squatting, bangs, ponytail, black hair, ahoge, serious, closed_mouth, black eyes, short_sleeves, wearing white shirt, wearing black skirt, sandals, white_background, simple_background, BREAK morning glory, (in front of potted morning glory:1.5), (writing in a notebook:1.3)'",
        },
        {
            "role": "user",
            "content": f"Now, please convert the following novel text: {text}, keeping the novel's background in mind.",
        },
    ]

    output = request_with_retry(messages)
    return output


# 定义一个函数，将文本翻译为分镜脚本
def translate_to_storyboard(text):
    messages = [
        {
            "role": "system",
            "content": "You are a professional storyboard assistant.This is very important if you encounter text such as <lora:add detail:1> and just skip it and keep this field!",
        },
        {
            "role": "user",
            "content": f"Based on the text \"{text}\", create a storyboard. Don't enumerate the storyboard content, but rather form a single, comprehensive and detailed sentence describing the background scenes, character appearances, and character actions. Note: avoid providing any information that isn't related to the background scenes, character appearances, or character actions!This is very important if you encounter text such as <lora:add detail:1> and just skip it and keep this field!",
        },
    ]
    return request_with_retry(messages)


# 发送POST请求
def s_post(url, data):
    return requests.post(
        url, data=json.dumps(data), headers={"Content-Type": "application/json"}
    )


def save_img(b64_image, path):
    os.makedirs(r"C:\do_video\image", exist_ok=True)
    with open(path, "wb") as file:
        file.write(base64.b64decode(b64_image))


def get_tts_audio_with_retry(text, language, index, retries=5, delay=5):
    provider = SpeechProvider()
    for i in range(retries):
        try:
            return provider.get_tts_audio(text, language, index)
        except Exception as e:
            if "429" in str(e):
                if i < retries - 1:
                    print(f"HTTP 429错误，等待{delay}秒后重试")
                    asyncio.sleep(delay)
                else:
                    print(f"HTTP 429错误，已达到最大重试次数")
                    raise
            else:
                raise


def choose_random_shot():
    shots = [
        "Close-up",
        "Extreme close-up",
        "Medium close-up",
        "Medium shot",
        "Medium long shot",
        "Long shot",
        "Extreme long shot",
        "Full shot",
        "Cowboy shot",
        "Bird's eye view",
        "Worm's eye view",
        "High angle",
        "Low angle",
        "Dutch angle",
        "Straight-on angle",
        "Over-the-shoulder shot",
        "Point-of-view shot",
        "Two-shot",
        "Three-shot",
        "Establishing shot",
        "Cutaway shot",
        "Reaction shot",
        "Insert shot",
        "Off-screen shot",
        "Reverse angle",
        "Top shot",
        "Bottom shot",
        "Tilt shot",
        "Pan shot",
        "Zoom in shot",
        "Zoom out shot",
        "Dolly in shot",
        "Dolly out shot",
        "Tracking shot",
        "Steadicam shot",
        "Handheld shot",
        "Crane shot",
        "Aerial shot",
        "Split screen shot",
        "Freeze frame shot",
    ]
    return random.choice(shots)


# 定义一个函数，将分镜转为提示词
def storyboard_to_prompt(text):
    messages = [
        {
            "role": "system",
            "content": "You are a professional storyboard assistant.This is very important if you encounter text such as <lora:add detail:1> and just skip it and keep this field!",
        },
        {
            "role": "user",
            "content": f"Based on the text \"{text}\", create a storyboard. Don't enumerate the storyboard content, but rather form a single, comprehensive and detailed sentence describing the background scenes, character appearances, and character actions. Note: avoid providing any information that isn't related to the background scenes, character appearances, or character actions!This is very important if you encounter text such as <lora:add detail:1> and just skip it and keep this field!",
        },
    ]
    return request_with_retry(messages)


# 定义函数，将mp3文件转换为wav格式
def convert_mp3_to_wav(mp3_path, wav_path):
    audio = AudioSegment.from_mp3(mp3_path)
    audio.export(wav_path, format="wav")


async def convert_text_to_audio(provider, text, language, output_path, audio_file_name):
    if not text:
        return False
    MAX_ATTEMPTS = 5
    attempt = 0
    wait_time = 1

    while attempt < MAX_ATTEMPTS:
        try:
            audio_format, audio_data = await provider.get_tts_audio(text, language)
            # 定义MP3和WAV的文件路径
            mp3_file_path = os.path.join(output_path, f"{audio_file_name}.mp3")
            wav_file_path = os.path.join(output_path, f"{audio_file_name}.wav")

            # 将获取到的音频数据写入MP3文件
            with open(mp3_file_path, "wb") as f:
                f.write(audio_data)

            # 将MP3文件转换为WAV格式
            convert_mp3_to_wav(mp3_file_path, wav_file_path)

            # 检查WAV文件是否生成成功
            if not os.path.exists(wav_file_path) or os.path.getsize(wav_file_path) == 0:
                raise Exception(f"音频文件生成失败或文件大小为0: {wav_file_path}")

            # 删除MP3文件
            os.remove(mp3_file_path)

            return wav_file_path
        except Exception as e:
            print(f"尝试 {attempt + 1} 失败，原因：{str(e)}。将在 {wait_time} 秒后重试。")
            await asyncio.sleep(wait_time)
            attempt += 1
            wait_time *= 2
        except exceptions.RateLimitException:
            print("超过速率限制。将在 60 秒后重试。")
            await asyncio.sleep(5)
    raise Exception(f"Failed to convert text to audio after {MAX_ATTEMPTS} attempts.")


MAX_CONCURRENT_TASKS = 10  # Adjust this value as needed


async def process_text_with_semaphore(sem, provider, text, language, output_dir, audio_file_name):
    async with sem:
        return await convert_text_to_audio(
            provider, text, language, output_dir, audio_file_name
        )


def process_text(texts, output_dir, language):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    sem = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
    provider = FreeSpeechProvider()

    tasks = []
    audio_files = []

    for i, text in enumerate(texts):
        task = loop.create_task(
            process_text_with_semaphore(
                sem, provider, text, language, output_dir, f"output_{i + 1}"
            )
        )
        tasks.append(task)

    progress_bar = tqdm(desc="正在生成配音音频", total=len(tasks), unit="files")

    while tasks:
        done, tasks = loop.run_until_complete(
            asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        )
        for task in done:
            try:
                audio_file = task.result()
                if audio_file:
                    progress_bar.update(1)
                    audio_files.append(audio_file)
            except exceptions.EdgeTTSException as e:
                progress_bar.write(f"发生错误：{str(e)}")
            except Exception as e:
                progress_bar.write(f"发生未知错误：{str(e)}")  # 捕获所有其他可能的异常，并输出相关信息
    # 确保所有任务完成
    if tasks:  # Add this check
        loop.run_until_complete(asyncio.wait(tasks))
    progress_bar.close()

    return sorted(audio_files)


def do_split_and_format(data_list, replace_dict):
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = []
        total_iterations = sum(len(data.split(", ")) for data in data_list)

        progress_bar = tqdm(total=total_iterations, desc="制作提示词")

        part_index = 0

        futures = []  # 创建一个空列表来存储future对象

        for data in data_list:
            parts = data.split(", ")
            for part in parts:
                text = part
                for old_text, new_text in replace_dict.items():
                    text = re.sub(old_text, new_text, text)

                future = executor.submit(do_prompt, text)
                futures.append(future)  # 添加future到列表中

                result.append(
                    {
                        "part": part,
                        "index": part_index,
                        "future": future,
                        "text": text,
                    }
                )

                part_index += 1

        for future in futures:  # 等待所有的任务完成
            future.result()  # 阻塞直到任务完成
            progress_bar.update()  # 然后更新进度条

        progress_bar.close()

        for res in result:
            res["translate"] = res["future"].result()
            del res["future"]

    return result


def extract_number(s):
    # 使用正则表达式提取字符串中的数字部分
    match = re.search(r"\d+", s)
    return int(match.group()) if match else -1  # 返回提取的整数，若未找到则返回-1


def custom_sort_key(item):
    return extract_number(item)  # 根据提取的数字大小进行排序


app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist2"),
)

# 创建一个全局的执行器，用来运行异步任务
executor = ThreadPoolExecutor()

# 制作提示词
@app.route("/to_video/do_free_video", methods=["POST"])
def do_free_video():
    global results, formatted_data_global, api_key
    data = request.get_json()
    replace_dict = data.get("replace_dict")
    text_num = data.get("text_num")
    text_area_value = data.get("textAreaValue")
    api_key = data.get("api_key")
    # Assuming text_area_value is a string that contains sentences
    sentences = text_area_value.split("\n")

    # 删除空句子，并将过短的句子与相邻的句子合并
    sentences = [s for s in sentences if len(s) > 0]
    # sentences = merge_short_sentences(sentences, text_num)  # 控制分句的长短，数字越小，语句越短，反之亦然
    formatted_data = do_split_and_format(sentences, replace_dict)

    # Store results in the global variable
    formatted_data_global = formatted_data
    results = formatted_data
    return jsonify({"code": 200, "data": formatted_data}), 200


# 重置提示词
@app.route("/to_video/do_word", methods=["POST"])
def do_word():
    global formatted_data_global
    data = request.get_json()
    text = data.get("part")
    word = do_prompt(text)

    # Store results in the global variable
    return jsonify({"code": 200, "data": word}), 200


# 制作声音
@app.route("/to_video/do_voice", methods=["POST"])
def do_voice():
    global results, audio_list_global
    data = request.get_json()
    language = data.get("language")

    # Parameter validation
    if not isinstance(language, dict):
        return jsonify({"code": 400, "message": "language must be a dictionary."}), 400

    # Get texts from global variable
    texts = [item["part"] for item in formatted_data_global]

    voice_dir = r"C:\do_video\voice"
    if not os.path.exists(voice_dir):
        os.makedirs(voice_dir)
    else:
        # 清空文件夹中的内容
        for filename in os.listdir(voice_dir):
            file_path = os.path.join(voice_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
    # 在一个新的线程中运行process_text函数，并阻塞等待结果
    with concurrent.futures.ThreadPoolExecutor() as executor:
        audio_files = executor.submit(
            process_text, texts, "C:\\do_video\\voice", language
        ).result()
    audio_files.sort(key=custom_sort_key)

    audio_list = [
        {"text": res, "voice_name": os.path.basename(audio_file)}
        for res, audio_file in zip(texts, audio_files)
    ]
    audio_list_global = audio_list

    return jsonify({"audio_list": audio_list}), 200



# 制作图片
@app.route("/to_video/do_plot", methods=["POST"])
def do_plot():
    global formatted_data_global, paint_url, result_out_list
    paint_set = request.get_json().get("paint_set")
    paint_url = request.get_json().get("sd_value")
    fiction = request.get_json().get("fiction")
    future_list = [i["translate"] for i in fiction]
    text_list = [i["part"] for i in fiction]
    out_list = []

    max_retries = 5
    delay_seconds = 5

    image_dir = r"C:\do_video\image"
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)
    else:
        # 清空文件夹中的内容
        for filename in os.listdir(image_dir):
            file_path = os.path.join(image_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

    with tqdm(total=len(fiction), desc="制作图片", disable=False) as t:
        for index2, res in enumerate(fiction):
            prompt = f"((best quality)), ((masterpiece)), (detailed),{res['translate']}"
            data = paint_set
            data["prompt"] = prompt

            for attempt in range(max_retries):
                try:
                    s_response = s_post(paint_url, data)
                    s_response.raise_for_status()
                except requests.exceptions.HTTPError as err:
                    print(f"错误：{err}")
                    if attempt < max_retries - 1:
                        print(f"等待{delay_seconds}秒后重试")
                        time.sleep(delay_seconds)
                    else:
                        print("请求失败，已达到最大重试次数")
                    continue
                image_path = os.path.join(image_dir, f"output_{index2 + 1}.png")
                save_img(s_response.json()["images"][0], image_path)
                res["image_path"] = f"output_{index2 + 1}.png"
                out_list.append(f"output_{index2 + 1}.png")
                break

            t.update()  # 这里无论请求是否成功，都表示已经处理过一个元素

    out_list.sort(key=custom_sort_key)
    result_out_list = [
        {"future": res, "texts": texts, "img_name": os.path.basename(audio_file)}
        for res, audio_file, texts in zip(future_list, out_list, text_list)
    ]
    return make_response({"img_list": result_out_list})


# 制作图片-测试
@app.route("/to_video/do_plot_test", methods=["POST"])
def do_plot_test():
    global result_out_list
    return make_response({"img_list": result_out_list})


# 图片重绘
@app.route("/to_video/redraw_plot", methods=["POST"])
def do_redraw_plot():
    global formatted_data_global, paint_url, result_out_list
    text = request.get_json().get("paint_set")
    image = request.get_json().get("image")
    print(f"{text}")
    s_response = s_post(paint_url, text)
    if s_response.status_code == 200:
        save_img(
            s_response.json()["images"][0],
            os.path.join(r"C:\do_video\image", f"{image}"),
        )
        print(f"{image}")
    else:
        print(f"错误：{s_response.status_code}")
    return jsonify({"code": 200}), 200


# 返回图片地址
@app.route("/to_video/images/<filename>")
def serve_image(filename):
    return send_from_directory("C:/do_video/image", filename)


# 返回语音地址
@app.route("/to_video/audio/<filename>")
def serve_audio(filename):
    return send_from_directory("C:/do_video/voice", filename)


# 添加关键帧
@app.route("/to_video/do_add_keys", methods=["POST"])
def do_add_keys():
    # file_ptth = "E:/txt_to_video/txt/had_result.txt"
    file_path = (
        request.get_json().get("file_path").replace("\\", "/").replace("\u202a", "")
    )
    print(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)

    # 轨道列表
    tracks = data["tracks"]
    # 音频列表
    audios = data["materials"]["audios"]
    # 视频列表
    videos = data["materials"]["videos"]
    # 遍历轨道
    for track in tracks:
        # 遍历段
        for segment in track["segments"]:
            # 遍历视频
            for video in videos:
                # 检查当前段是否与当前视频匹配
                if segment["material_id"] == video["id"]:
                    height = video["height"]
                    width = video["width"]
                    keyframe_scale = {
                        "id": str(uuid.uuid4()).upper(),
                        "keyframe_list": [
                            {
                                "curveType": "Line",
                                "graphID": "",
                                "id": str(uuid.uuid4()).upper(),
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "time_offset": 0,
                                "values": [1.3, 1.3],
                            },
                            {
                                "curveType": "Line",
                                "graphID": "",
                                "id": str(uuid.uuid4()).upper(),
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "time_offset": segment["source_timerange"]["duration"],
                                "values": [1.3, 1.3],
                            },
                        ],
                        "property_type": "KFTypeScale",
                    }

                    other_keyframes = [
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [width * -0.000195],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [width * 0.000195],
                                },
                            ],
                            "property_type": "KFTypePositionX",
                        },
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [width * 0.000195],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [width * -0.000195],
                                },
                            ],
                            "property_type": "KFTypePositionX",
                        },
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [height * -0.00027],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [height * 0.00027],
                                },
                            ],
                            "property_type": "KFTypePositionY",
                        },
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [height * 0.00027],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [height * -0.00027],
                                },
                            ],
                            "property_type": "KFTypePositionY",
                        },
                    ]

                    segment["common_keyframes"].append(keyframe_scale)

                    # Randomly choose a keyframe from the other keyframes list
                    chosen_keyframe = random.choice(other_keyframes)

                    # Add the chosen keyframe to the segment
                    segment["common_keyframes"].append(chosen_keyframe)

        # Write JSON file

        # if __name__ == '__main__':
        #     print(tracks)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    return make_response({"code": 200})


# 添加x关键帧
@app.route("/to_video/do_add_xkeys", methods=["POST"])
def do_add_xkeys():
    # file_ptth = "E:/txt_to_video/txt/had_result.txt"
    file_path = (
        request.get_json().get("file_path").replace("\\", "/").replace("\u202a", "")
    )
    print(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)
    # 定义索引
    index = 0
    # 轨道列表
    tracks = data["tracks"]
    # 音频列表
    audios = data["materials"]["audios"]
    # 视频列表
    videos = data["materials"]["videos"]
    # 遍历轨道
    for track in tracks:
        # 遍历段
        for segment in track["segments"]:
            # 遍历视频
            for video in videos:
                # 检查当前段是否与当前视频匹配
                if segment["material_id"] == video["id"]:
                    height = video["height"]
                    width = video["width"]
                    keyframe_scale = {
                        "id": str(uuid.uuid4()).upper(),
                        "keyframe_list": [
                            {
                                "curveType": "Line",
                                "graphID": "",
                                "id": str(uuid.uuid4()).upper(),
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "time_offset": 0,
                                "values": [1.3, 1.3],
                            },
                            {
                                "curveType": "Line",
                                "graphID": "",
                                "id": str(uuid.uuid4()).upper(),
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "time_offset": segment["source_timerange"]["duration"],
                                "values": [1.3, 1.3],
                            },
                        ],
                        "property_type": "KFTypeScale",
                    }

                    other_keyframes = [
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [width * -0.000195],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [width * 0.000195],
                                },
                            ],
                            "property_type": "KFTypePositionX",
                        },
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [width * 0.000195],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [width * -0.000195],
                                },
                            ],
                            "property_type": "KFTypePositionX",
                        },
                    ]

                    segment["common_keyframes"].append(keyframe_scale)

                    # 交替选择一个keyframe
                    chosen_keyframe = other_keyframes[index]
                    segment["common_keyframes"].append(chosen_keyframe)

                    # 索引递增并取余，以实现交替索引
                    index = (index + 1) % len(other_keyframes)

                    # Add the chosen keyframe to the segment
                    segment["common_keyframes"].append(chosen_keyframe)

        # Write JSON file

        # if __name__ == '__main__':
        #     print(tracks)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    return make_response({"code": 200})


# 添加y关键帧
@app.route("/to_video/do_add_ykeys", methods=["POST"])
def do_add_ykeys():
    # file_ptth = "E:/txt_to_video/txt/had_result.txt"
    file_path = (
        request.get_json().get("file_path").replace("\\", "/").replace("\u202a", "")
    )
    print(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)
    # 定义索引
    index = 0
    # 轨道列表
    tracks = data["tracks"]
    # 音频列表
    audios = data["materials"]["audios"]
    # 视频列表
    videos = data["materials"]["videos"]
    # 遍历轨道
    for track in tracks:
        # 遍历段
        for segment in track["segments"]:
            # 遍历视频
            for video in videos:
                # 检查当前段是否与当前视频匹配
                if segment["material_id"] == video["id"]:
                    height = video["height"]
                    width = video["width"]
                    keyframe_scale = {
                        "id": str(uuid.uuid4()).upper(),
                        "keyframe_list": [
                            {
                                "curveType": "Line",
                                "graphID": "",
                                "id": str(uuid.uuid4()).upper(),
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "time_offset": 0,
                                "values": [1.3, 1.3],
                            },
                            {
                                "curveType": "Line",
                                "graphID": "",
                                "id": str(uuid.uuid4()).upper(),
                                "left_control": {"x": 0.0, "y": 0.0},
                                "right_control": {"x": 0.0, "y": 0.0},
                                "time_offset": segment["source_timerange"]["duration"],
                                "values": [1.3, 1.3],
                            },
                        ],
                        "property_type": "KFTypeScale",
                    }

                    other_keyframes = [
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [height * -0.00027],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [height * 0.00027],
                                },
                            ],
                            "property_type": "KFTypePositionY",
                        },
                        {
                            "id": str(uuid.uuid4()).upper(),
                            "keyframe_list": [
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": 0,
                                    "values": [height * 0.00027],
                                },
                                {
                                    "curveType": "Line",
                                    "graphID": "",
                                    "id": str(uuid.uuid4()).upper(),
                                    "left_control": {"x": 0.0, "y": 0.0},
                                    "right_control": {"x": 0.0, "y": 0.0},
                                    "time_offset": segment["source_timerange"][
                                        "duration"
                                    ],
                                    "values": [height * -0.00027],
                                },
                            ],
                            "property_type": "KFTypePositionY",
                        },
                    ]

                    segment["common_keyframes"].append(keyframe_scale)

                    # 交替选择一个keyframe
                    chosen_keyframe = other_keyframes[index]
                    segment["common_keyframes"].append(chosen_keyframe)

                    # 索引递增并取余，以实现交替索引
                    index = (index + 1) % len(other_keyframes)

                    # Add the chosen keyframe to the segment
                    segment["common_keyframes"].append(chosen_keyframe)

        # Write JSON file

        # if __name__ == '__main__':
        #     print(tracks)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    return make_response({"code": 200})


# 添加入场出场动画
@app.route("/to_video/do_enter", methods=["POST"])
def do_enter():
    # file_ptth = "E:/txt_to_video/txt/had_result.txt"
    file_path = (
        request.get_json().get("file_path").replace("\\", "/").replace("\u202a", "")
    )
    print(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)
    # 定义索引
    index = 0
    # 轨道列表
    tracks = data["tracks"]
    # 入场
    material_animations = data["materials"]["material_animations"]
    # 视频列表
    videos = data["materials"]["videos"]
    # 遍历轨道
    for track in tracks:
        # 遍历段
        for segment in track["segments"]:
            if track.get("type") == "video":
                # 遍历视频
                id = str(uuid.uuid4()).upper()
                segment["extra_material_refs"].append(id)

                if (
                    segment.get("common_keyframes")
                    and len(segment["common_keyframes"]) > 0
                    and len(segment["common_keyframes"][0].get("keyframe_list", [])) > 1
                ):
                    time = segment["common_keyframes"][0]["keyframe_list"][1][
                        "time_offset"
                    ]
                else:
                    time = 0  # 或者其他默认值

                print(time)
                materia_p = {
                    "animations": [
                        {
                            "anim_adjust_params": None,
                            "category_id": "入场",
                            "category_name": "in",
                            "duration": 500000,
                            "id": "431662",
                            "material_type": "video",
                            "name": "动感放大",
                            "panel": "video",
                            "path": "C:/Users/12438/AppData/Local/JianyingPro/User Data/Cache/effect/431662/3d880239a1fa70fbaedcc7fd20794e22",
                            "platform": "all",
                            "resource_id": "6740867832570974733",
                            "start": 0,
                            "type": "in",
                        },
                        {
                            "anim_adjust_params": None,
                            "category_id": "出场",
                            "category_name": "out",
                            "duration": 500000,
                            "id": "629083",
                            "material_type": "video",
                            "name": "轻微放大",
                            "panel": "video",
                            "path": "C:/Users/12438/AppData/Local/JianyingPro/User Data/Cache/effect/629083/b2a1271b065aa9e6351bfd64ff7d4eea",
                            "platform": "all",
                            "resource_id": "6800268611807089166",
                            "start": time - 50000,
                            "type": "out",
                        },
                    ],
                    "id": id,
                    "type": "sticker_animation",
                }
                material_animations.append(materia_p)

            # Write JSON file

            # if __name__ == '__main__':
            #     print(tracks)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

    return make_response({"code": 200})


# 音视频对齐
@app.route("/to_video/do_align", methods=["POST"])
def do_align():
    # file_ptth = "E:/txt_to_video/txt/had_result.txt"
    file_path = (
        request.get_json().get("file_path").replace("\\", "/").replace("\u202a", "")
    )
    print(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)

    # Find the video track and its segments' timerange values
    video_source_timeranges = []
    video_target_timeranges = []
    for track in data["tracks"]:
        if track["type"] == "audio":
            for segment in track["segments"]:
                video_source_timeranges.append(segment["source_timerange"])
                video_target_timeranges.append(segment["target_timerange"])
            break

    # If video timerange values were found, update the audio timerange values
    if video_source_timeranges and video_target_timeranges:
        for track in data["tracks"]:
            if track["type"] == "video":
                for i, segment in enumerate(track["segments"]):
                    if i < len(video_source_timeranges) and i < len(
                        video_target_timeranges
                    ):
                        segment["source_timerange"] = video_source_timeranges[i]
                        segment["target_timerange"] = video_target_timeranges[i]

    # Write JSON file
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return make_response({"code": 200})


# 静音消除
@app.route("/to_video/mute_canc", methods=["POST"])
def mute_canc():
    def remove_silence_from_audio(file_path, output_path, top_db=30):
        # 读取音频文件
        y, sr = librosa.load(file_path)

        # 确定音频信号的每一帧是否静音
        non_mute = librosa.effects.split(y, top_db=top_db)

        # 输出无静音部分的音频
        non_mute_audio = []
        for i in non_mute:
            non_mute_audio.extend(y[i[0] : i[1]])

        # 保存到新的文件中
        sf.write(output_path, non_mute_audio, sr)

    # 输入音频文件夹路径
    input_folder = "C:\\do_video\\voice"

    # 输出音频文件夹路径
    output_folder = "C:\\do_video\\voice2"

    # 确保输出文件夹存在
    os.makedirs(output_folder, exist_ok=True)

    # 遍历文件夹中的每个文件
    for file_name in os.listdir(input_folder):
        # 确定文件的完整路径
        input_file_path = os.path.join(input_folder, file_name)

        # 确定输出文件的完整路径
        output_file_path = os.path.join(output_folder, file_name)

        # 删除静音部分
        remove_silence_from_audio(input_file_path, output_file_path)

    return make_response({"code": 200})


# 打开文件夹
@app.route("/to_video/open_pictures", methods=["GET"])
def open_pictures():
    folder_path = "C:\\do_video\\image"  # 请将路径替换为您想打开的文件夹路径
    os.startfile(folder_path)
    return make_response({"code": 200})


# 打开文件夹
@app.route("/to_video/open_voice", methods=["GET"])
def open_voice():
    folder_path = "C:\\do_video\\voice"  # 请将路径替换为您想打开的文件夹路径
    os.startfile(folder_path)
    return make_response({"code": 200})


@app.route("/")
def index():
    return send_file(os.path.join(app.static_folder, "", "index.html"))


@app.route("/<path:file>")
def file_handler(file):
    file_path = os.path.join(app.static_folder, "", file)
    if os.path.exists(file_path):
        return send_file(file_path)
    else:
        abort(404, "File not found")


def open_browser():
    webbrowser.open_new("http://127.0.0.1:12002/")


if __name__ == "__main__":
    Timer(3, open_browser).start()
    app.run(host="127.0.0.1", port=12002)
