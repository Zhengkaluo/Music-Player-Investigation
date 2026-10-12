#!/usr/bin/env python3
"""Regression checks for the title-only, review-only context scan."""
import json
import unittest
from pathlib import Path

import scan_title_contexts as scan


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
        self.assertIn("weather.wind", self.associations("季风 (Monsoon)", "Fayzz"))
        self.assertIn("weather.snow", self.associations("Snow(Hey Oh)", "Red Hot Chili Peppers"))

    def test_artist_never_used_for_matching(self):
        self.assertFalse(self.associations("Soulmate", "April Rain"))
        self.assertFalse(self.associations("The Road", "As The Stars Fall"))
        self.assertFalse(self.associations("Room 27", "Rejjie Snow"))

    def test_case_and_width(self):
        self.assertIn("season.summer", self.associations("ＳＵＭＭＥＲ"))
        item = self.associations("ＳＵＭＭＥＲ")["season.summer"]
        self.assertEqual(item["evidence"][0]["matched_text"], "ＳＵＭＭＥＲ")
        self.assertIn("weather.fog", self.associations("走入有霧的森林"))
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
        self.assertIn("time.night", tags)

    def test_no_cascading_inference(self):
        self.assertNotIn("season.autumn", self.associations("September"))
        self.assertNotIn("holiday.christmas", self.associations("Snowy Sky"))
        self.assertNotIn("season.winter", self.associations("Urban Snow"))
        self.assertNotIn("solar_term.bailu", self.associations("Morning Dew"))
        self.assertNotIn("weather.clear", self.associations("Sunshine"))
        self.assertFalse(any(tag.startswith("calendar.date.") for tag in self.associations("Red Moon")))

    def test_weather_idioms(self):
        self.assertNotIn("weather.clear", self.associations("東京晴れ舞台", "sucola"))
        self.assertNotIn("weather.rain", self.associations("Cold Meteor Showers", "The Breathing Effect"))
        self.assertNotIn("weather.temperature_warm", self.associations("i miss your warm hands", "i don't like mirrors"))
        self.assertIn("weather.cloud_then_clear", self.associations("阴转晴"))
        self.assertIn("weather.rain_then_clear", self.associations("showers with sunny intervals"))

    def test_clocks_and_units(self):
        for title, tag in [("2AM in New York", "time.clock.02:00"), ("5Am Waltz", "time.clock.05:00"), ("pm7:42", "time.clock.19:42")]:
            self.assertIn(tag, self.associations(title))
        self.assertEqual(self.associations("4:55")["time.clock_unspecified"]["title_judgment"], "ambiguous")
        self.assertIn("weather.temperature_cold", self.associations("0℃の日曜", "STUTS, SIKK-O, 铃木真海子"))
        self.assertNotIn("weather.temperature_cold", self.associations("10℃の日曜"))
        self.assertNotIn("time.dawn", self.associations("Before Dawn", "Men I Trust"))
        self.assertIn("time.predawn", self.associations("Before Dawn", "Men I Trust"))

    def test_whole_library_integrity(self):
        source = scan.SONGBASE / "song_base_by_artist.json"
        before = scan.digest(source)
        result = scan.build_scan(source, self.config, self.reviews)
        self.assertEqual(scan.digest(source), before)
        self.assertEqual(len(result["tracks"]), 1161)
        self.assertEqual(result["summary"]["input_rows"], 1162)
        self.assertEqual(result["summary"]["duplicate_rows_collapsed"], 1)
        self.assertEqual(result["summary"]["tracks_with_candidates"] + result["summary"]["tracks_without_candidates"], 1161)
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
