#!/usr/bin/env python3
"""Regression checks for the title-only, review-only context scan."""
import json
import unittest

import scan_title_contexts as scan

STORE_EXCLUDED_TAGS = {
    "weather.ice", "weather.dew", "holiday.graduation",
    "weather.clouds", "weather.snow", "weather.wind", "time.night",
    "light.sky", "light.moon", "time.predawn", "time.dawn",
    "time.clock_unspecified", "light.aurora", "light.generic",
    'season.all',
    'weather.fog',
    'weather.storm',
    'weather.thunder',
    'weather.frost',
    'weather.temperature_warm',
    'weather.wind_lull',
    'weather.temperature_reference',
    'holiday.birthday',
    'holiday.generic',
    'holiday.celebration',
    'calendar.traditional_month03',
    'time.midnight',
    'light.sun',
    'light.moonlight',
    'light.golden_hour',
    'activity.food_drink',
    'activity.picnic',
    'activity.work',
    'activity.cycling',
    'activity.dance',
    'place.window',
    'place.veranda',
    'place.mountain_forest',
    'nature.plants',
    'event.gifting',
}


class TitleContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = scan.load_json(scan.BASE / "title_context_rules.json")
        cls.reviews = scan.load_json(scan.BASE / "title_context_semantic_reviews.json")
        cls.compiled = scan.compile_rules(cls.config)

    def associations(self, title, artist="fixture"):
        items, _, _ = scan.scan_title(title, artist, self.config, self.compiled, self.reviews)
        return {item["tag"]: item for item in items}

    def test_word_boundaries(self):
        fixtures = ["Rewind", "Venice", "Twice As Nice", "a slice of peach", "Windbreaker", "Fallow Tide", "Dontmakemefallinlove", "Sunglasses", "sunflowers", "holidaymaker", "delight", "Song (Live at Night)"]
        for title in fixtures:
            tags = self.associations(title)
            for forbidden in ["weather.wind", "weather.ice", "season.autumn", "light.sun", "holiday.generic", "light.generic", "time.night"]:
                self.assertNotIn(forbidden, tags, title)

    def test_month_boundary(self):
        tags = self.associations("十一月十二月")
        self.assertIn("calendar.month11", tags)
        self.assertIn("calendar.month12", tags)
        self.assertNotIn("calendar.month01", tags)
        self.assertNotIn("calendar.month02", tags)

    def test_credit_does_not_supply_context(self):
        self.assertFalse(self.associations("Flow feat. Sunset Rollercoaster 落日飞车", "杨乃文, 落日飛車"))
        self.assertFalse(self.associations("Song (feat. April Rain)"))
        self.assertFalse(self.associations("Song [Live at Night]"))
        self.assertIn("season.summer", self.associations("Song (Summer)"))
        self.assertIn("light.evening", self.associations("Song (Sunset)"))

    def test_artist_never_used_for_matching(self):
        self.assertFalse(self.associations("Soulmate", "April Rain"))
        self.assertFalse(self.associations("The Road", "As The Stars Fall"))
        self.assertFalse(self.associations("Room 27", "Rejjie Snow"))

    def test_case_and_width(self):
        self.assertIn("season.summer", self.associations("ＳＵＭＭＥＲ"))
        item = self.associations("ＳＵＭＭＥＲ")["season.summer"]
        self.assertEqual(item["evidence"][0]["matched_text"], "ＳＵＭＭＥＲ")
        self.assertFalse(self.associations("走入有霧的森林"))
        self.assertIn("solar_term.jingzhe", self.associations("驚蟄"))

    def test_dates(self):
        cases = [("August 10", "08-10"), ("August Twelve", "08-12"), ("May Ninth", "05-09"), ("september 13th", "09-13"), ("Dec.27", "12-27"), ("November 15, 2023", "2023-11-15")]
        for title, value in cases:
            item = self.associations(title, "Khruangbin" if title == "May Ninth" else "fixture")["calendar.date." + value]
            self.assertFalse(item["trigger_hint"]["enabled"])
            self.assertEqual(item["trigger_hint"]["recurrence"], "not_configured")
        self.assertFalse(any(tag.startswith("calendar.date.") for tag in self.associations("February 30")))
        self.assertFalse(any(tag.startswith("calendar.date.") for tag in self.associations("Etude No. 3 Op. 10/3")))
        self.assertNotIn("calendar.month03", self.associations("Mars 2027", "青葉市子"))

    def test_ambiguous_season(self):
        self.assertEqual(self.associations("Fall", "Chon")["season.autumn"]["title_judgment"], "ambiguous")
        self.assertNotIn("season.autumn", self.associations("A Fall and Rebirth", "Re:Plus"))
        self.assertEqual(self.associations("Indian Summer", "Banzo, Satbyeol")["season.summer"]["title_judgment"], "ambiguous")
        self.assertEqual(self.associations("Sakura", "RIOPY")["season.spring"]["title_judgment"], "indirect")

    def test_multiple_contexts(self):
        tags = self.associations("时间回到秋天的下午", "狄奥尼索斯乐队")
        self.assertIn("season.autumn", tags)
        self.assertIn("time.afternoon", tags)
        tags = self.associations("Summer Nights", "Lil' Rob")
        self.assertIn("season.summer", tags)
        self.assertNotIn("time.night", tags)
        tags = self.associations("穿过雾雨森林", "Cicada")
        self.assertIn("weather.rain", tags)
        self.assertNotIn("weather.fog", tags)

    def test_no_cascading_inference(self):
        self.assertNotIn("season.autumn", self.associations("September"))
        self.assertNotIn("holiday.christmas", self.associations("Snowy Sky"))
        self.assertNotIn("season.winter", self.associations("Urban Snow"))
        self.assertNotIn("solar_term.bailu", self.associations("Morning Dew"))
        self.assertIn("weather.clear", self.associations("Sunshine"))
        self.assertFalse(self.associations("Sun"))
        self.assertFalse(any(tag.startswith("calendar.date.") for tag in self.associations("Red Moon")))

    def test_weather_idioms(self):
        self.assertNotIn("weather.clear", self.associations("東京晴れ舞台", "sucola"))
        self.assertNotIn("weather.rain", self.associations("Cold Meteor Showers", "The Breathing Effect"))
        self.assertNotIn("weather.temperature_warm", self.associations("i miss your warm hands", "i don't like mirrors"))
        self.assertEqual(set(self.associations("阴转晴")), {"weather.overcast", "weather.clear"})
        self.assertEqual(set(self.associations("showers with sunny intervals")), {"weather.rain", "weather.clear"})

    def test_clocks_and_units(self):
        for title, tag in [("2AM in New York", "time.clock.02:00"), ("5Am Waltz", "time.clock.05:00"), ("pm7:42", "time.clock.19:42")]:
            self.assertNotIn(tag, self.associations(title))
        self.assertNotIn("time.clock_unspecified", self.associations("4:55"))
        self.assertNotIn("weather.temperature_cold", self.associations("0℃の日曜", "STUTS, SIKK-O, 铃木真海子"))
        self.assertNotIn("weather.temperature_cold", self.associations("10℃の日曜"))
        self.assertFalse(self.associations("Before Dawn", "Men I Trust"))
        self.assertIn("light.sunrise", self.associations("Morning Sunrise", "Yazmin Lacey"))
        self.assertIn("time.morning", self.associations("Morning Sunrise", "Yazmin Lacey"))

    def test_confirmed_store_groups(self):
        tags = self.associations("傍晚 黄昏 暮色 日落 夕阳 晚霞", "fixture")
        self.assertEqual(set(tags), {"light.evening"})
        self.assertEqual(tags["light.evening"]["label"], "傍晚天光")
        self.assertGreater(len(tags["light.evening"]["evidence"]), 5)
        self.assertGreater(len(tags["light.evening"]["source_associations"]), 1)
        self.assertTrue(tags["light.evening"]["trigger_hint"]["requires_opening_hours_overlap"])
        self.assertFalse(self.associations("Sunrise")["light.sunrise"]["trigger_hint"]["requires_actual_sunrise_overlap"])
        self.assertEqual(set(self.associations("Cold Cool")), {"weather.temperature_cold"})
        self.assertEqual(set(self.associations("Morning Ante Meridiem")), {"time.morning"})
        self.assertEqual(set(self.associations("Noon")), {"time.midday"})
        self.assertEqual(set(self.associations("Afternoon PM")), {"time.afternoon"})
        self.assertEqual(self.associations("Siesta Freestyle")["time.afternoon"]["title_judgment"], "indirect")
        for title in ["Four Seasons", "4seasons", "月の光", "Moonlight", "Sun", "Living Frost", "Happy Birthday", "Holiday", "弥生", "Plantasia", "山行", "Coffee", "80°F"]:
            self.assertFalse(self.associations(title), title)

    def test_clock_window_and_period_boundaries(self):
        for title, expected in [("8 AM", "time.morning"), ("10:59 AM", "time.morning"), ("11 AM", "time.midday"), ("1 PM", "time.midday"), ("2 PM", "time.afternoon"), ("5:59 PM", "time.afternoon")]:
            tags = self.associations(title)
            self.assertEqual(set(tags), {expected}, title)
            self.assertEqual(tags[expected]["source_associations"][0]["trigger_hint"]["kind"], "clock_reference")
        for title in ["7:59 AM", "6 PM", "7 PM", "2 AM", "5 AM"]:
            self.assertFalse(self.associations(title), title)

    def test_weather_change_shares_evidence_group(self):
        for title in ["showers with sunny intervals", "雨后放晴", "阴转晴"]:
            items = self.associations(title)
            self.assertEqual(len(items), 2, title)
            groups = {g for a in items.values() for g in a["scoring_groups"]}
            self.assertEqual(len(groups), 1, title)
            self.assertTrue(any(a.get("weather_changes") for a in items.values()))
            self.assertFalse(any(t in items for t in ["weather.rain_then_clear", "weather.cloud_then_clear"]))
        for title in ["May Ninth", "Sunday Weekend"]:
            items = self.associations(title)
            self.assertEqual(len({g for a in items.values() for g in a["scoring_groups"]}), 1, title)

    def test_title_false_positives_remain_unapproved(self):
        for title, artist in [("Right As Rain", "Adele"), ("Sunny Side Up", "Surfaces"), ("Let's Fall in Love for the Night", "FINNEAS")]:
            self.assertFalse(self.associations(title, artist), title)
        item = self.associations("Tone Twilight Zone", "CORNELIUS")["light.evening"]
        self.assertEqual(item["title_judgment"], "ambiguous")
        self.assertEqual(item["source_associations"][0]["tag"], "time.dusk")
        self.assertEqual(self.associations("Avril 14th")["calendar.date.04-14"]["title_judgment"], "explicit")
        self.assertIn("season.winter", self.associations("我独自过冬"))
        self.assertEqual(len([r for r in self.config["rules"] if r["id"].startswith("solar_term.")]), 24)
        self.assertEqual(len([r for r in self.config["rules"] if r["id"].startswith("holiday.")]), 10)
        self.assertEqual(self.config["manual_themes"][0]["activation"], "manual_only")

    def test_removed_store_contexts(self):
        blocked = STORE_EXCLUDED_TAGS
        self.assertEqual(set(self.config["policy"]["excluded_tags"]), blocked)
        self.assertFalse(any(rule.get("tag", rule["id"]) in blocked for rule in self.config["rules"]))
        self.assertFalse(any(review["tag"] in blocked for review in self.reviews["reviews"]))
        fixtures = ["Ice Copy", "想像一块冰的迁徙", "氷の鳥", "Morning Dew", "Graduation Song", "冰", "露水", "毕业纪念", "Clouds", "Urban Snow", "季风 (Monsoon)", "Chinook", "Windspeaks", "Nighttime", "夜班车", "Cielo", "Moon", "Before Dawn", "Vargtimme", "黎明", "4:55", "AURORA", "Light", "Hicari"]
        for title in fixtures:
            self.assertTrue(blocked.isdisjoint(self.associations(title)), title)
        self.assertIn("time.morning", self.associations("Morning Dew"))
        self.assertIn("solar_term.bailu", self.associations("白露"))
        self.assertIn("solar_term.xiaoxue", self.associations("小雪"))
        self.assertIn("weather.clear", self.associations("Blue Sky", "GYVUS"))
        self.assertFalse(self.associations("Night Squall", "Balmorhea"))
        self.assertFalse(self.associations("Moonlight Becomes You", "北村英治"))
        self.assertIn("light.evening", self.associations("夕阳消失之前", "Cicada"))
        self.assertEqual(set(self.associations("夕凪", "羊文学")), {"light.evening"})
        added_rule = {"id": "weather.wind", "category": "weather", "label": "风意象", "match_mode": "word", "aliases": ["winds"], "strength": "explicit"}
        compiled = scan.compile_rules(dict(self.config, rules=self.config["rules"] + [added_rule]))
        result, _, _ = scan.scan_title("Summer Winds", "fixture", self.config, compiled, self.reviews)
        self.assertFalse(any(item["tag"] in blocked for item in result))
        added_reviews = {"reviews": [{"title": "Summer Winds", "artist": "fixture", "tag": "season.summer", "action": "explicit", "reason": "测试语义附加项收口。", "add": [{"tag": "weather.wind", "category": "weather", "label": "风意象", "matched_text": "Winds", "strength": "explicit", "note": "测试已排除项。"}]}], "title_safeguards": []}
        result, _, _ = scan.scan_title("Summer Winds", "fixture", self.config, self.compiled, added_reviews)
        self.assertFalse(any(item["tag"] in blocked for item in result))
        result = scan.build_scan(scan.SONGBASE / "song_base_by_artist.json", self.config, self.reviews)
        self.assertTrue(all(item["tag"] not in blocked for track in result["tracks"].values() for item in track["associations"]))

    def test_whole_library_integrity(self):
        source = scan.SONGBASE / "song_base_by_artist.json"
        before = scan.digest(source)
        result = scan.build_scan(source, self.config, self.reviews)
        self.assertEqual(scan.digest(source), before)
        library = scan.load_json(source)
        rows = [song for singer in library["singers"] for song in singer["songs"]]
        unique_ids = {scan.MID_RE.search(song["qq_music"]).group(1) for song in rows}
        self.assertEqual(len(result["tracks"]), len(unique_ids))
        self.assertEqual(result["summary"]["input_rows"], len(rows))
        self.assertEqual(result["summary"]["duplicate_rows_collapsed"], len(rows) - len(unique_ids))
        self.assertEqual(result["summary"]["tracks_with_candidates"] + result["summary"]["tracks_without_candidates"], len(unique_ids))
        self.assertEqual(len(result["tracks"]["qq:000dpx1K39ZkOj"]["source_records"]), 2)
        for tid, track in result["tracks"].items():
            self.assertEqual(tid, track["track_id"])
            self.assertEqual(len({a["tag"] for a in track["associations"]}), len(track["associations"]))
            for association in track["associations"]:
                self.assertEqual(association["review_status"], "pending")
                self.assertFalse(association["auto_lock_allowed"])
                self.assertFalse(association["trigger_hint"]["enabled"])
                for evidence in association["evidence"]:
                    start, end = evidence["span"]
                    self.assertEqual(evidence["source_title"][start:end], evidence["matched_text"])
        report = scan.html_report(result)
        self.assertNotIn("@@", report)
        self.assertEqual(report.count('data-kind="'), result["summary"]["total_associations"])
        self.assertEqual(json.loads(json.dumps(result))["summary"], result["summary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
