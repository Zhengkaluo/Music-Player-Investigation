#!/usr/bin/env python3
"""批量标注专辑 genres/region/noise_level (基于知识库)"""
import json
from pathlib import Path

DATA_DIR = Path('data')
ALBUMS_FILE = DATA_DIR / 'albums.json'

# ── 知识库: 艺人 → (genres, region, noise_level) ──
ARTIST_GENRE_MAP = {
    # Classical / Neo-classical
    'Ludovico Einaudi': (['neo-classical', 'classical'], '意大利', 2.0),
    'Tony Ann': (['neo-classical', 'piano'], '加拿大', 3.0),
    'Dennis Kuo': (['ambient', 'piano', 'lofi'], '美国', 2.5),

    # Jazz
    'FKJ': (['jazz', 'electronic', 'funk'], '法国', 4.0),
    'Nujabes': (['jazz hiphop', 'lofi', 'hiphop'], '日本', 4.0),
    'Pat Metheny': (['fusion jazz', 'jazz'], '美国', 4.0),
    'GONTITI': (['contemporary-jazz', 'acoustic'], '日本', 3.0),
    'Billie Holiday': (['jazz', 'cool jazz'], '美国', 2.5),
    'Hank Williams': (['country', 'folk'], '美国', 3.0),
    'Johnny Cash': (['country', 'folk', 'rock'], '美国', 3.5),
    'Bruno Major': (['R&B', 'soul', 'jazz'], '英国', 3.5),
    'Uyama Hiroto': (['jazz hiphop', 'electronic', 'lofi'], '日本', 3.5),
    'Bahamas Is Afie': (['indie-folk', 'soul', 'acoustic'], '巴哈马', 3.0),
    'Stacey Kent': (['jazz', 'cool jazz'], '美国', 3.0),
    'Michael Bublé': (['jazz', 'pop', 'traditional pop'], '加拿大', 3.5),
    'Kat Edmonson': (['jazz', 'traditional pop', 'swing'], '美国', 3.0),
    'Masego': (['jazz', 'hiphop', 'R&B'], '美国', 4.5),
    '中村遥': (['jazz', 'bossa nova'], '日本', 3.0),
    'Ardhito Pramono': (['jazz pop', 'R&B'], '印尼', 4.0),

    # Post-rock / Math-rock
    '落日飛車': (['dream pop', 'indie-rock', 'soft rock'], '台湾', 5.0),
    'Chinese Football': (['math-rock', 'emo', 'post-rock'], '大陆', 5.5),
    'Cicada': (['post-rock', 'ambient', 'new-classical'], '台湾', 3.0),
    'Toe': (['math-rock', 'post-rock'], '日本', 5.5),
    '惘闻': (['ambient-rock', 'post-rock'], '大陆', 5.5),
    '丁可': (['ambient', 'dream pop', 'neoclassical'], '大陆', 2.5),
    'World\'s End Girlfriend': (['post-rock', 'classical', 'experimental'], '日本', 4.0),
    'The Cinematic Orchestra': (['modern jazz', 'post-rock', 'cinematic'], '英国', 3.5),
    'Fayzz': (['math-rock', 'post-rock'], '大陆', 5.0),
    'Shanghai Qiutian': (['indie-rock', 'math-rock', 'post-hardcore'], '中国/英国', 6.0),
    '缺省': (['post-rock', 'shoegaze', 'indie-rock'], '大陆', 5.0),

    # Indie / Rock
    'TV Girl': (['Alternative Rock', 'Lofi', 'electronic'], '美国', 4.0),
    'RADWIMPS': (['indie-rock', 'alternative rock', 'pop rock'], '日本', 5.0),
    '椎名林檎': (['j-pop', 'rock', 'experimental'], '日本', 5.5),
    '羊文学': (['indie-rock', 'j-pop', 'alternative'], '日本', 4.5),
    'Jeff Buckley': (['indie-rock', 'folk-rock', 'alternative rock'], '美国', 5.0),
    'Tom Odell': (['piano rock', 'indie-pop'], '英国', 4.0),
    'Sufjan Stevens': (['indie-folk', 'baroque pop'], '美国', 3.5),
    'Car Seat Headrest': (['indie-rock', 'lo-fi rock'], '美国', 5.5),
    'The 1975': (['indie-pop', 'synth-pop', 'alternative rock'], '英国', 4.5),
    'Green Day': (['punk rock', 'alternative rock'], '美国', 7.0),
    'Coldplay': (['alternative rock', 'pop rock', 'britpop'], '英国', 4.5),
    'The Beatles': (['rock', 'pop rock', 'classic rock'], '英国', 4.0),
    'The Velvet Underground': (['alternative rock', 'art rock'], '美国', 5.0),
    "The La's": (['indie-rock', 'britpop'], '英国', 5.0),
    'Cage The Elephant': (['alternative rock', 'garage rock'], '美国', 6.5),
    'OneRepublic': (['pop rock', 'alternative rock'], '美国', 4.5),
    'Imagine Dragons': (['alternative rock', 'pop rock', 'electropop'], '美国', 5.5),
    'Linkin Park': (['alternative rock', 'nu metal', 'rap rock'], '美国', 8.0),
    'Nothing More': (['alternative metal', 'hard rock'], '美国', 8.0),
    '盘尼西林乐队': (['indie-rock', 'britpop'], '大陆', 5.5),
    '岛屿心情': (['indie-rock', 'alternative rock'], '大陆', 5.5),
    '黑屋乐队': (['indie-rock', 'alternative rock'], '大陆', 5.5),
    '痛仰乐队': (['rock', 'punk rock', 'alternative rock'], '大陆', 7.0),
    '纵贯线': (['mandopop', 'rock', 'pop'], '台湾', 5.0),
    'Pink Floyd': (['progressive rock', 'psychedelic rock', 'art rock'], '英国', 5.5),
    'Electric Light Orchestra': (['rock', 'symphonic rock'], '英国', 5.0),
    'Prince': (['funk', 'R&B', 'pop rock', 'psychedelic'], '美国', 5.5),
    'Love': (['indie-rock', 'noise rock', 'shoegaze'], '韩国', 5.5),
    'Carsick Cars': (['indie-rock', 'noise rock'], '大陆', 7.0),
    '理想真魔王乐队': (['indie-rock', 'alternative rock'], '大陆', 5.0),
    '九连真人': (['indie-rock', 'folk rock', 'hakka rock'], '大陆', 5.5),

    # Electronic / Ambient
    '鲸鱼马戏团': (['ambient', 'post-rock', 'cinematic'], '大陆', 2.0),
    'mamerico': (['ambient', 'new-classical', 'minimalist'], '日本', 2.0),
    'iwamizu': (['ambient', 'electronic', 'lofi'], '日本', 2.0),
    'Aura Safari': (['ambient', 'downtempo', 'electronic'], '韩国', 3.0),
    'Bcalm': (['electronic', 'lofi', 'chillwave'], '韩国', 3.5),
    'Forest306': (['electronic', 'ambient', 'chillout'], '日本', 3.0),
    '92914': (['R&B', 'korean r&b', 'urban'], '韩国', 4.0),
    'Alexer Lyton': (['electronic', 'ambient', 'cinematic'], '未知', 3.0),
    'Alan Walker': (['electronic', 'edm', 'progressive house'], '挪威', 5.5),
    'The Chainsmokers': (['electronic', 'edm', 'pop'], '美国', 5.5),
    'Ekali': (['electronic', 'future bass', 'ambient'], '加拿大', 4.5),
    'BowAsWell': (['electronic', 'funk', 'synthesizer'], '大陆', 5.1),
    'Hang Øver': (['electronic', 'ambient', 'lofi'], '未知', 3.5),
    'SILICON ESTATE': (['electronic', 'ambient', 'lofi'], '未知', 3.0),
    'Daniel Lanois': (['ambient', 'folk', 'atmospheric rock'], '加拿大', 3.5),
    'Andrew Prahlow': (['ambient', 'soundtrack', 'space ambient'], '美国', 2.0),
    'Lana Del Rey': (['dream pop', 'baroque pop'], '美国', 4.0),

    # Folk / Acoustic
    'Josh Ritter': (['indie-folk', 'folk rock'], '美国', 3.5),
    'Rosie Thomas': (['indie-folk', 'singer-songwriter', 'acoustic'], '美国', 2.5),
    'Joel Hanson': (['indie-folk', 'folk', 'acoustic'], '美国', 3.0),
    'Edith Whiskers': (['indie-folk', 'acoustic', 'lofi folk'], '未知', 2.0),
    'Conan Gray': (['pop', 'indie-pop', 'singer-songwriter'], '美国', 4.0),
    'VH (Vast & Hazy)': (['indie-rock', 'folk rock'], '台湾', 5.0),
    '浅堤': (['indie-rock', 'emotional rock', 'folk rock'], '台湾', 5.0),
    '海尾巴': (['indie-folk', 'folk', 'singer-songwriter'], '大陆', 3.0),
    '还潮': (['indie-folk', '宁波话 folk', 'experimental folk'], '大陆', 3.5),
    '风子': (['indie-folk', 'folk', 'singer-songwriter'], '大陆', 3.5),
    '孟慧圆': (['indie-folk', 'folk', 'singer-songwriter'], '大陆', 3.0),
    '赵雷': (['indie-folk', 'folk', 'chinese folk'], '大陆', 3.5),
    '以莉·高露': (['indie-folk', 'folk', 'taiwanese folk'], '台湾', 3.0),
    '谢春花': (['indie-folk', 'folk', 'mandopop'], '大陆', 3.5),
    '张悬': (['indie-folk', 'folk', 'singer-songwriter'], '台湾', 3.5),
    '王忆灵': (['indie-folk', 'folk'], '大陆', 3.0),
    'Bon Iver': (['indie-folk', 'indie-rock', 'folktronica'], '美国', 3.5),
    'Novo Amor': (['indie-folk', 'folk', 'ambient folk'], '爱尔兰', 3.0),
    'Brandi Carlile': (['indie-folk', 'country rock'], '美国', 4.5),
    'Regina Spektor': (['indie-pop', 'anti-folk', 'baroque pop'], '美国', 4.0),
    'Matt Corby': (['soul', 'folk', 'indie-folk'], '澳大利亚', 3.5),
    'Mree': (['indie-folk', 'dream pop'], '美国', 3.5),
    'Russian Red': (['indie-folk', 'folk'], '西班牙', 3.0),
    'Carla Morrison': (['indie-pop', 'latin pop', 'dream pop'], '墨西哥', 3.5),
    'Joshua Hyslop': (['indie-folk', 'folk'], '加拿大', 3.0),
    'Lucid Green': (['indie-folk', 'folk'], '美国', 3.5),
    'Luisa Sobral': (['indie-folk', 'folk'], '葡萄牙', 3.0),
    '#1 Dads': (['indie-folk', 'folk'], '澳大利亚', 3.0),
    'Anson Seabra': (['indie-folk', 'singer-songwriter'], '巴西', 3.5),
    'Aaron Taylor': (['indie-folk', 'folk'], '英国', 3.0),
    'JNR Williams': (['indie-folk', 'soul'], '新西兰', 3.5),
    'Neo Retros': (['indie-pop', 'folk pop', 'acoustic'], '波兰', 3.5),
    'Willis': (['indie-folk', 'folk', 'acoustic'], '台湾', 3.5),
    'Pajaro Sunrise': (['indie-folk', 'folk'], '西班牙', 3.5),
    '制造木屋': (['indie-folk', 'folk', 'acoustic'], '大陆', 3.5),
    '低苦艾乐队': (['indie-folk', 'folk rock', 'chinese folk'], '大陆', 4.5),
    'ROTH BART BARON': (['indie-folk', 'folk', 'art pop'], '日本', 4.0),
    '関取花': (['indie-folk', 'folk', 'japanese folk'], '日本', 3.5),
    '七尾旅人': (['indie-folk', 'experimental'], '日本', 4.0),
    'Humbert Humbert': (['indie-folk', 'folk', 'acoustic'], '日本', 3.0),
    '青葉市子': (['indie-folk', 'fingerstyle guitar', 'acoustic'], '日本', 3.0),
    'Isaac Gracie': (['indie-folk', 'singer-songwriter', 'soul'], '英国', 4.0),
    '羊毛とおはな': (['indie-folk', 'folk', 'japanese indie'], '日本', 3.0),
    '在忠': (['indie-folk', 'folk'], '大陆', 3.5),
    '马良': (['indie-folk', 'folk', 'singer-songwriter'], '大陆', 3.0),
    '薛德勇': (['indie-folk', 'folk'], '大陆', 3.0),
    '柯智棠': (['indie-folk', 'folk'], '台湾', 3.0),
    '金永所': (['indie-folk', 'folk'], '韩国', 3.5),
    '骑自行车的风景': (['indie-folk', 'folk'], '大陆', 3.5),
    'George Ezra': (['folk-pop', 'blues rock'], '英国', 4.0),
    'Surfaces': (['pop', 'feel-good pop', 'folk-pop'], '美国', 3.5),

    # Singer-Songwriter / Pop
    'John Legend': (['R&B', 'soul', 'pop'], '美国', 4.0),
    'Jason Mraz': (['pop', 'acoustic pop', 'singer-songwriter'], '美国', 4.0),
    'Bruno Mars': (['pop', 'R&B', 'funk'], '美国', 4.5),
    'Sam Smith': (['pop', 'R&B', 'soul'], '英国', 4.0),
    'Ed Sheeran': (['pop', 'folk-pop', 'singer-songwriter'], '英国', 4.0),
    'Adele': (['pop', 'soul', 'R&B'], '英国', 4.0),
    'Shawn Mendes': (['pop', 'folk-pop'], '加拿大', 4.0),
    'Taylor Swift': (['country pop', 'pop', 'folk-pop'], '美国', 4.0),
    'Billie Eilish': (['pop', 'electropop', 'alt-pop'], '美国', 4.0),
    'FINNEAS': (['pop', 'electropop', 'indie-pop'], '美国', 4.0),
    'Anne-Marie': (['pop', 'British pop', 'R&B'], '英国', 4.5),
    'MIKA': (['pop', 'glam pop', 'synth-pop'], '英国', 5.0),
    'Mac Demarco': (['indie-rock', 'lo-fi rock'], '加拿大', 4.5),
    'Post Malone': (['hiphop', 'pop rap', 'R&B'], '美国', 5.0),
    'Mac Miller': (['hiphop', 'jazz rap', 'alternative hip hop'], '美国', 5.0),
    'Frank Ocean': (['R&B', 'alternative R&B', 'experimental'], '美国', 4.5),
    'ZAYN': (['pop', 'R&B', 'soul'], '英国', 4.5),
    'Elton John': (['pop', 'rock', 'piano rock'], '英国', 4.5),
    'Cyndi Lauper': (['pop', '80s pop', 'rock'], '美国', 5.0),
    'Frank Sinatra': (['traditional pop', 'swing', 'jazz'], '美国', 3.0),
    'Jim Reeves': (['country', 'traditional pop'], '美国', 3.0),
    'Jimmie Rodgers': (['country', 'folk', 'bluegrass'], '美国', 3.5),
    'Rod Stewart': (['rock', 'soft rock', 'blue-eyed soul'], '英国', 4.5),
    'Pitbull': (['pop', 'reggaeton', 'dance pop'], '美国', 6.0),
    'Boz Scaggs': (['blue-eyed soul', 'soft rock', 'R&B'], '美国', 4.0),
    'Leon Bridges': (['soul', 'R&B', 'southern soul'], '美国', 4.0),
    'Tom Rosenthal': (['indie-pop', 'anti-folk'], '英国', 3.5),
    'Saint Motel': (['indie-pop', 'art pop', 'indie-rock'], '美国', 5.0),
    'Sophie Hunger': (['indie-pop', 'soul', 'folk'], '瑞士', 4.0),
    'Barcelona': (['indie-pop', 'pop rock'], '美国', 4.5),
    'Whilk': (['soul', 'R&B', 'pop'], '英国', 4.0),
    'McFly': (['pop rock', 'power pop', 'britpop'], '英国', 5.0),
    'One Direction': (['pop', 'boy band', 'pop rock'], '英国/爱尔兰', 4.5),
    'Keira Knightley': (['pop', 'indie-pop', 'folk pop'], '英国', 4.0),  # Begin Again
    'Matt Corby': ('dup', None, None),  # duplicate key handled below
    'Matt Maltese': (['indie-pop', 'baroque pop'], '英国', 4.0),
    'Berhana': (['R&B', 'soul', 'psychedelic soul'], '美国', 4.5),
    'Anthony Lazaro': (['indie-pop', 'singer-songwriter'], '美国', 3.5),
    'Ivy Adara': (['pop', 'dance pop', 'electropop'], '澳大利亚', 4.5),
    'Sophie Rose': (['pop', 'dance pop', 'country pop'], '美国', 4.5),
    'Savoir Adore': (['indie-pop', 'synth-pop', 'dream pop'], '美国', 4.5),
    'Tai Verdes': (['pop', 'pop rock', 'singer-songwriter'], '美国', 4.5),
    'GIVĒON': (['R&B', 'soul', 'pop'], '美国', 4.0),
    'Juliette Armanet': (['chanson', 'french pop'], '法国', 3.5),
    'Boyce Avenue': (['acoustic', 'pop', 'cover band'], '美国', 3.5),
    'ThimLife': (['R&B', 'soul', 'lofi'], '未知', 4.0),

    # Hiphop / Rap
    'Rich Brian': (['hiphop', 'trap', 'asian hip hop'], '印尼', 5.5),
    'XXXTentacion': (['hiphop', 'emotional rap', 'alternative R&B'], '美国', 6.0),
    '法老': (['hiphop', 'chinese hiphop', 'hardcore rap'], '大陆', 6.5),
    '杨和苏KeyNG': (['hiphop', 'trap', 'hardcore rap'], '大陆', 7.0),
    '圣代': (['hiphop', 'Chinese hiphop', 'narrative rap'], '大陆', 5.5),
    'Ice Paper': (['hiphop', 'r&b', 'melodic rap'], '大陆', 5.0),
    'Vince Staples': ('dup', None, None),
    'sadeyes': (['hiphop', 'emotional rap', 'lofi hip hop'], '美国', 4.5),
    'Rejjie Snow': (['hiphop', 'alternative hip hop', 'soul'], '爱尔兰', 5.0),
    'ARAI': (['hiphop', 'japanese hiphop', 'R&B'], '日本', 5.0),
    'Limbo': (['electronic', 'hiphop', 'experimental'], '未知', 5.0),
    'fcj': (['hiphop', 'lofi hiphop', 'jazz rap'], '未知', 5.0),
    '10keys beats': (['hiphop', 'lofi hip hop'], '韩国', 5.0),
    'Saber梁维嘉': (['hiphop', 'chinese hiphop'], '大陆', 6.0),
    '王以太': (['hiphop', 'melodic rap', 'R&B'], '大陆', 5.0),
    '荒诞故事': ('dup', None, None),

    # R&B / Soul
    '鮮于貞娥': (['R&B', 'alternative R&B', 'korean indie'], '韩国', 4.5),
    'SOLOMON': (['R&B', 'soul', 'pop'], '美国', 4.5),
    'Appleby': (['soul', 'R&B', 'singer-songwriter'], '美国', 4.0),
    'Ashlee': (['R&B', 'soul', 'indie-pop'], '美国', 4.0),
    'Make Major': (['R&B', 'soul', 'neo-soul'], '未知', 4.0),
    'Faime': (['R&B', 'soul', 'indie-pop'], '未知', 4.0),
    'Colde': (['R&B', 'korean R&B', 'urban'], '韩国', 4.0),
    'Healy': (['R&B', 'indie-pop', 'soul'], '英国', 4.0),
    '壞特?te': (['R&B', 'soul', 'indie-pop'], '台湾', 4.5),
    'Sam Ock': (['R&B', 'christian R&B', 'singer-songwriter'], '美国', 4.0),
    'Hudson Thames': (['R&B', 'soul', 'pop'], '美国', 4.0),
    'NAO': (['R&B', 'electronica', 'UK garage'], '英国', 4.5),
    'Sarah Kang': (['R&B', 'indie-pop', 'lofi'], '韩国', 4.0),
    'Christian Kuria': (['R&B', 'soul', 'afrobeats'], '德国', 4.0),
    'Ulena': (['indie-pop', 'dream pop', 'korean indie'], '韩国', 4.0),
    'NIKI': (['R&B', 'indonesian pop', 'indie-pop'], '印尼', 4.0),
    'Galdive': (['R&B', 'indonesian pop', 'lofi'], '印尼', 4.0),
    'vietra': (['R&B', 'indonesian pop', 'soul'], '印尼', 4.0),
    'Peachy!': (['R&B', 'lofi R&B', 'indie-pop'], '韩国', 4.0),
    'Peach Tree Rascals': (['R&B', 'hiphop soul', 'lofi'], '美国', 4.5),
    '沈以诚': (['R&B', 'soul', 'singer-songwriter'], '大陆', 4.0),
    'HENRY刘宪华': (['pop', 'R&B', 'mandopop'], '韩国/加拿大', 4.5),
    'Tiwa Savage': (['afrobeats', 'pop', 'R&B'], '尼日利亚', 5.5),
    'Davido': (['afrobeats', 'afro pop', 'dance'], '尼日利亚', 6.5),

    # Indie-Pop / Bedroom Pop / Lofi
    'mxmtoon': (['indie-pop', 'lofi pop', 'bedroom pop'], '美国', 3.5),
    'clairo': (['bedroom pop', 'indie-pop', 'lofi'], '美国', 3.5),
    'Cuco': (['Latin pop', 'bedroom pop', 'lofi R&B'], '美国', 4.5),
    'Still Woozy': (['bedroom pop', 'psychedelic pop', 'indie-pop'], '美国', 4.5),
    'Lowswimmer': (['bedroom pop', 'indie-pop', 'dream pop'], '英国', 4.0),
    'Neeks': (['indie-pop', 'bedroom pop', 'lofi'], '加拿大', 3.5),
    'Chevy': (['lofi', 'indie-pop', 'bedroom pop'], '未知', 3.5),
    'Trap the Moon': (['R&B', 'lofi', 'soul'], '未知', 4.0),
    'When the Summer Ends': ('dup', None, None),

    # Chinese Indie / Mandopop
    '椅子乐团 The Chairs': (['indie-folk', 'folk rock', 'taiwanese indie'], '台湾', 4.0),
    '郑宜农': (['indie-folk', 'folk rock', 'taiwanese indie'], '台湾', 4.0),
    '宇宙人': (['indie-pop', 'alternative pop', 'pop rock'], '台湾', 4.5),
    '旺福': (['pop', 'indie-pop', 'taiwanese pop'], '台湾', 4.5),
    '旅行团乐队': (['indie-rock', 'pop rock', 'alternative rock'], '大陆', 5.0),
    '表情银行': (['indie-rock', 'dream pop', 'electronic'], '大陆', 4.5),
    'Crispy脆乐团': (['indie-pop', 'indie-rock', 'taiwanese indie'], '台湾', 4.5),
    'SoulFa 灵魂沙发': (['indie-pop', 'folk pop', 'taiwanese indie'], '台湾', 4.0),
    'ZaZaZsu咂咂苏': (['indie-pop', 'dream pop', 'bedroom pop'], '大陆', 4.0),
    'Ruby Pan 潘子爵': (['indie-pop', 'singer-songwriter', 'mandopop'], '台湾', 4.0),
    'Kiri T': (['R&B', 'indie-pop', 'cantonese pop'], '香港', 4.0),
    '陈婧霏': (['indie-pop', 'dream pop', 'singer-songwriter'], '大陆', 4.0),
    '祁紫檀': (['indie-folk', 'art pop', 'experimental folk'], '大陆', 4.0),
    '树莉莉 Serrini': (['indie-pop', 'dream pop', 'cantopop art'], '香港', 4.5),
    '吴芊仪': (['indie-pop', 'singer-songwriter', 'mandopop'], '台湾', 4.0),
    '张蔓莎': (['indie-pop', 'cantopop', 'R&B'], '香港', 4.5),
    '张蔓姿': (['indie-pop', 'cantopop', 'dream pop'], '香港', 4.5),
    '卫兰': (['cantopop', 'R&B', 'pop'], '香港', 4.0),
    '万芳': (['mandopop', 'folk', 'taiwanese pop'], '台湾', 3.5),
    '小霞': (['folk', 'singer-songwriter', 'mandopop'], '大陆', 3.5),
    '许巍': (['folk rock', 'chinese rock', 'singer-songwriter'], '大陆', 4.5),
    '伍佰': (['rock', 'taiwanese rock', 'mandopop'], '台湾', 5.5),
    '朴树': (['folk rock', 'indie-folk', 'singer-songwriter'], '大陆', 4.0),
    '韦礼安': (['mandopop', 'indie-pop', 'singer-songwriter'], '台湾', 4.0),
    '刘悦spam': (['indie-pop', 'singer-songwriter'], '大陆', 4.0),
    '朱恩池ZGODZ': (['indie-pop', 'singer-songwriter', 'mandopop'], '大陆', 4.0),
    '李想Evelyn': (['indie-pop', 'singer-songwriter', 'dream pop'], '大陆', 4.0),
    '宋瑀哲': (['indie-pop', 'singer-songwriter'], '大陆', 4.0),
    '水星': (['indie-folk', 'singer-songwriter', 'dream pop'], '大陆', 3.5),
    '田梦成': (['indie-pop', 'singer-songwriter'], '大陆', 4.0),
    '歪歪歪': (['indie-pop', 'singer-songwriter'], '大陆', 4.0),
    '恰恰恰恰恰恰': (['indie-pop', 'singer-songwriter'], '大陆', 4.0),
    '唐人踢': (['indie-folk', 'folk', 'experimental'], '大陆', 4.0),
    '海底时光机': (['indie-rock', 'folk rock', 'dream pop'], '大陆', 4.5),
    '景德镇文艺复兴': (['indie-folk', 'folk', 'art pop'], '大陆', 4.0),
    '绿橄榄': (['indie-rock', 'folk rock', 'singer-songwriter'], '大陆', 4.5),
    '恐龙的皮': (['dream pop', 'indie-pop'], '大陆', 6.0),
    '阿肆': (['indie-pop', 'singer-songwriter', 'pop'], '大陆', 4.0),
    'Leo1Bee': (['indie-pop', 'dream pop', 'R&B'], '大陆', 4.0),
    'LÜCY': (['indie-pop', 'jazz pop', 'R&B'], '台湾', 4.0),
    '何欣穗': (['indie-pop', 'jazz pop', 'taiwanese indie'], '台湾', 4.0),
    '张亚东': (['soundtrack', 'electronic', 'ambient'], '大陆', 3.5),
    '孙骁': (['folk', 'chinese folk', 'rock'], '大陆', 4.5),
    '易烊千玺': (['pop', 'mandopop', 'R&B'], '大陆', 4.0),
    '梁博': (['rock', 'blues rock', 'singer-songwriter'], '大陆', 5.0),
    'Aimee Mann': (['indie-rock', 'alternative rock', 'singer-songwriter'], '美国', 4.5),

    # Japanese
    '藤井风': (['R&B', 'soul', 'japanese urban'], '日本', 4.5),
    '宇多田光': (['J-pop', 'R&B', 'electropop'], '日本', 4.0),
    '山崎将义': (['J-pop', 'folk', 'singer-songwriter'], '日本', 4.0),
    'imase': (['J-pop', 'city pop', 'electropop'], '日本', 4.5),
    'ari': (['indie-pop', 'J-pop', 'singer-songwriter'], '日本', 4.0),
    'kanekoayano': (['indie-rock', 'j-indie', 'shoegaze'], '日本', 4.5),
    'Runrun': (['indie-pop', 'japanese indie', 'dream pop'], '日本', 4.0),
    'LUCKY TAPE': (['city pop', 'soul', 'funk'], '日本', 4.5),
    'Daoko': (['J-pop', 'electropop'], '日本', 4.5),
    'Rie Fu': (['J-pop', 'indie-pop', 'folk pop'], '日本', 4.0),
    'yonawo': (['indie-pop', 'japanese indie'], '日本', 4.0),

    # Korean
    'Deli Spice': (['indie-pop', 'korean indie', 'pop rock'], '韩国', 4.5),
    '李笛': (['indie-folk', 'korean folk', 'soundtrack'], '韩国', 3.5),
    '咖啡少年': (['indie-pop', 'korean indie'], '韩国', 4.0),
    '해리안 윤소안': (['indie-folk', 'korean folk'], '韩国', 3.0),

    # Soundtrack / Classical
    'Hans Zimmer': (['soundtrack', 'orchestral', 'cinematic'], '德国', 5.0),
    'Bear McCreary': (['soundtrack', 'orchestral', 'experimental'], '美国', 5.0),
    'Jocelyn Pook': (['contemporary classical', 'soundtrack', 'ambient'], '英国', 2.5),
    'PASCALS': (['ambient', 'new-classical', 'soundtrack'], '日本', 2.5),
    'Carl Orrje Piano Ensemble': (['classical', 'soundtrack', 'piano'], '瑞典', 2.5),
    'Wulfin Lieske': (['classical', 'guitar classical'], '德国', 3.0),
    'Take 3 - The City of Prague Philharmonic Orchestra': (['classical', 'orchestral', 'soundtrack'], '捷克', 3.0),
    '英雄联盟': (['soundtrack', 'orchestral', 'electronic'], '美国', 5.0),
    'Michael Jackson': (['pop', 'R&B', 'soul'], '美国', 5.0),
    'Spongebob Squarepants': (['soundtrack', 'children music'], '美国', 4.0),
}

def main():
    albums = json.loads(ALBUMS_FILE.read_text(encoding='utf-8'))
    pending = [a for a in albums if not a.get('genres')]

    matched = 0
    unknown = []

    for album in pending:
        artist = album['artist']
        info = ARTIST_GENRE_MAP.get(artist)
        if info and info[0] != 'dup':
            genres, region, noise = info
            album['genres'] = genres
            if region:
                album['region'] = region
            if noise:
                album['noise_level'] = noise
            album['noise_source'] = 'estimated'
            matched += 1
        elif artist not in [x[0] for x in unknown]:
            unknown.append((artist, album['name']))

    ALBUMS_FILE.write_text(json.dumps(albums, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f'知识库命中: {matched} 张')
    print(f'未识别: {len(unknown)} 人')
    if unknown:
        print('\n未识别艺人:')
        for art, alb in unknown:
            print(f'  ? {art} - {alb}')

if __name__ == '__main__':
    main()
