from __future__ import annotations

from pathlib import Path
import plistlib
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from article_importer.configuration import Schedule, load_config
from article_importer.schedule_config import add_schedule_config
from article_importer.scheduling import (
    ScheduleChange,
    ScheduleInfo,
    apply_schedules,
    cron_line,
    install_schedule,
    launchd_plist,
    remove_schedule,
    schedule_info,
    schedule_status,
    windows_create_arguments,
)
from article_importer.workspace import WorkspaceError, initialize_workspace


class SchedulingRenderingTests(unittest.TestCase):
    def test_windows_npm_shim_runs_through_command_processor(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.touch()
            with (
                patch(
                    "article_importer.scheduling.shutil.which",
                    return_value=r"C:\Program Files\nodejs\opmlark.cmd",
                ),
                patch("article_importer.scheduling._platform", return_value="windows"),
            ):
                info = schedule_info(config)

            self.assertTrue(info.command.startswith('cmd.exe /D /C ""'))
            self.assertIn("opmlark.cmd", info.command)
            self.assertIn("scheduler.log", info.command)

    def test_temporary_npx_command_is_rejected_for_schedule(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.touch()
            with patch(
                "article_importer.scheduling.shutil.which",
                return_value=r"C:\cache\_npx\123\opmlark.cmd",
            ):
                with self.assertRaisesRegex(WorkspaceError, "temporary npx"):
                    schedule_info(config)

    def test_same_workspace_schedule_ids_and_other_workspaces_get_distinct_names(self) -> None:
        with TemporaryDirectory() as directory:
            first = Path(directory) / "one" / "reading" / "config.toml"
            second = Path(directory) / "two" / "reading" / "config.toml"
            with patch("article_importer.scheduling.shutil.which", return_value="opmlark"):
                morning = schedule_info(first, Schedule("morning", "daily", "07:00"))
                evening = schedule_info(first, Schedule("evening", "daily", "19:00"))
                other = schedule_info(second, Schedule("morning", "daily", "07:00"))

            self.assertEqual(3, len({morning.name, evening.name, other.name}))

    def test_linux_cron_renders_every_recurrence_and_marks_each_id(self) -> None:
        info = ScheduleInfo("cron", "name", "07:00", "opmlark run", "job")
        cases = {
            Schedule("daily", "daily", "07:05"): "5 7 * * *",
            Schedule("weekly", "weekly", "09:30", days=("mon", "fri")): "30 9 * * mon,fri",
            Schedule("monthly", "monthly", "18:10", day=31): "10 18 31 * *",
            Schedule("once", "once", "12:00", date="2026-09-15"): "0 12 15 9 *",
        }
        for schedule, prefix in cases.items():
            with self.subTest(schedule=schedule.id):
                line = cron_line(Path("/tmp/config.toml"), schedule, info)
                self.assertTrue(line.startswith(prefix))
                self.assertIn(f":{schedule.id}", line)
                if schedule.frequency == "once":
                    self.assertIn("2026-09-15", line)

    def test_windows_arguments_translate_every_recurrence(self) -> None:
        info = ScheduleInfo("windows", "OPMLark task", "07:00", "opmlark run", "job")
        cases = (
            (Schedule("daily", "daily", "07:00"), ("/SC", "DAILY")),
            (Schedule("weekly", "weekly", "09:30", days=("sat", "sun")), ("/D", "SAT,SUN")),
            (Schedule("monthly", "monthly", "18:00", day=15), ("/D", "15")),
            (Schedule("once", "once", "12:00", date="2026-09-15"), ("/SD", "2026-09-15")),
        )
        with patch("article_importer.scheduling._windows_start_date", return_value="15/09/2026"):
            for schedule, expected_pair in cases:
                with self.subTest(schedule=schedule.id):
                    arguments = windows_create_arguments(info, schedule)
                    position = arguments.index(expected_pair[0])
                    expected = "15/09/2026" if schedule.frequency == "once" else expected_pair[1]
                    self.assertEqual(expected, arguments[position + 1])

    def test_launchd_plist_uses_calendar_intervals_and_date_guard(self) -> None:
        info = ScheduleInfo("launchd", "io.opmlark.test.once", "12:00", "opmlark run", "once")
        payload = plistlib.loads(
            launchd_plist(
                Path("/tmp/config.toml"),
                Schedule("once", "once", "12:00", date="2026-09-15"),
                info,
            )
        )

        self.assertEqual("io.opmlark.test.once", payload["Label"])
        self.assertEqual({"Month": 9, "Day": 15, "Hour": 12, "Minute": 0}, payload["StartCalendarInterval"])
        self.assertIn("2026-09-15", payload["ProgramArguments"][-1])


class SchedulingReconciliationTests(unittest.TestCase):
    def test_legacy_default_install_and_remove_aliases_update_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            with (
                patch("article_importer.scheduling._platform", return_value="cron"),
                patch("article_importer.scheduling.shutil.which", return_value="/usr/bin/opmlark"),
                patch(
                    "article_importer.scheduling.apply_schedules",
                    return_value=(ScheduleChange("default", "created"),),
                ),
            ):
                installed = install_schedule(config, "06:45")
                with patch(
                    "article_importer.scheduling.remove_native_schedule",
                    return_value=ScheduleChange("default", "removed"),
                ):
                    removed = remove_schedule(config)

            self.assertEqual("06:45", installed.time)
            self.assertEqual(installed.name, removed.name)
            self.assertEqual((), load_config(config).schedules)

    def test_cron_apply_reconciles_multiple_entries_and_preserves_unrelated_lines(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            add_schedule_config(config, Schedule("evening", "daily", "19:00"))
            add_schedule_config(config, Schedule("disabled", "daily", "12:00", False))
            with (
                patch("article_importer.scheduling._platform", return_value="cron"),
                patch("article_importer.scheduling.shutil.which", return_value="/usr/bin/opmlark"),
                patch("article_importer.scheduling._read_crontab") as read,
                patch("article_importer.scheduling._write_crontab") as write,
            ):
                digest = schedule_info(config, Schedule("morning", "daily", "07:00")).name.split(" - ")[-2]
                read.return_value = f"0 1 * * * unrelated\n0 2 * * * old # opmlark:{digest}:stale\n"
                changes = apply_schedules(config)

            contents = write.call_args.args[0]
            self.assertIn("unrelated", contents)
            self.assertIn(":morning", contents)
            self.assertIn(":evening", contents)
            self.assertNotIn(":disabled", contents)
            self.assertNotIn(":stale", contents)
            self.assertEqual({"morning", "evening", "disabled", "stale"}, {item.id for item in changes})

    def test_cron_status_reports_installed_missing_disabled_and_stale(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("installed", "daily", "07:00"))
            add_schedule_config(config, Schedule("missing", "daily", "08:00"))
            add_schedule_config(config, Schedule("disabled", "daily", "09:00", False))
            with (
                patch("article_importer.scheduling._platform", return_value="cron"),
                patch("article_importer.scheduling.shutil.which", return_value="/usr/bin/opmlark"),
            ):
                installed_info = schedule_info(config, Schedule("installed", "daily", "07:00"))
                current = cron_line(config, Schedule("installed", "daily", "07:00"), installed_info)
                digest = installed_info.name.split(" - ")[-2]
                with patch(
                    "article_importer.scheduling._read_crontab",
                    return_value=current + f"\n0 1 * * * old # opmlark:{digest}:stale\n",
                ):
                    statuses = schedule_status(config)

            self.assertEqual(
                {
                    "installed": "installed",
                    "missing": "missing",
                    "disabled": "disabled",
                    "stale": "stale",
                },
                {item.id: item.action for item in statuses},
            )

    def test_status_reports_disabled_native_artifact_as_drift(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("disabled", "daily", "09:00", False))
            with (
                patch("article_importer.scheduling._platform", return_value="cron"),
                patch("article_importer.scheduling.shutil.which", return_value="/usr/bin/opmlark"),
            ):
                info = schedule_info(config, Schedule("disabled", "daily", "09:00", False))
                with patch("article_importer.scheduling._read_crontab", return_value=cron_line(config, Schedule("disabled", "daily", "09:00"), info)):
                    statuses = schedule_status(config)

            self.assertEqual("drifted", statuses[0].action)

    def test_windows_apply_continues_after_one_schedule_fails(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("first", "daily", "07:00"))
            add_schedule_config(config, Schedule("second", "daily", "08:00"))

            def run(arguments: list[str]) -> None:
                if "first" in arguments[arguments.index("/TN") + 1]:
                    raise WorkspaceError("denied")

            with (
                patch("article_importer.scheduling._platform", return_value="windows"),
                patch("article_importer.scheduling.shutil.which", return_value=r"C:\bin\opmlark.cmd"),
                patch("article_importer.scheduling._windows_managed", return_value={}),
                patch("article_importer.scheduling._run_checked", side_effect=run) as checked,
            ):
                changes = apply_schedules(config)

            self.assertEqual(2, checked.call_count)
            self.assertEqual(
                {"first": ("failed", False), "second": ("created", True)},
                {item.id: (item.action, item.ok) for item in changes},
            )

    def test_windows_discovery_failure_is_reported_for_each_schedule(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            add_schedule_config(config, Schedule("evening", "daily", "19:00"))
            with (
                patch("article_importer.scheduling._platform", return_value="windows"),
                patch("article_importer.scheduling._windows_managed", side_effect=WorkspaceError("denied")),
            ):
                changes = apply_schedules(config)

            self.assertEqual(
                {"morning": False, "evening": False},
                {item.id: item.ok for item in changes},
            )

    def test_windows_apply_reports_unchanged_when_native_task_matches(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            with (
                patch("article_importer.scheduling._platform", return_value="windows"),
                patch("article_importer.scheduling.shutil.which", return_value=r"C:\bin\opmlark.cmd"),
                patch("article_importer.scheduling._windows_managed", return_value={"morning": "native-name"}),
                patch("article_importer.scheduling._windows_task_matches", return_value=True),
                patch("article_importer.scheduling._run_checked") as checked,
            ):
                changes = apply_schedules(config)

            self.assertEqual("unchanged", changes[0].action)
            checked.assert_not_called()

    def test_windows_task_xml_is_compared_with_desired_trigger_and_action(self) -> None:
        from article_importer.scheduling import _windows_task_matches

        schedule = Schedule("weekend", "weekly", "09:30", days=("sat", "sun"))
        info = ScheduleInfo(
            "windows",
            "OPMLark task",
            "09:30",
            'cmd.exe /D /C "opmlark run --config C:\\workspace\\config.toml"',
            "weekend",
        )
        xml = """<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Triggers><CalendarTrigger><StartBoundary>2026-08-02T09:30:00</StartBoundary>
          <ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Saturday/><Sunday/></DaysOfWeek></ScheduleByWeek>
          </CalendarTrigger></Triggers><Actions><Exec><Command>cmd.exe</Command>
          <Arguments>/D /C "opmlark run --config C:\\workspace\\config.toml"</Arguments>
          </Exec></Actions></Task>"""
        result = type("Result", (), {"returncode": 0, "stdout": xml})()
        with patch("article_importer.scheduling.subprocess.run", return_value=result):
            self.assertTrue(_windows_task_matches("OPMLark task", info, schedule))
            self.assertFalse(
                _windows_task_matches(
                    "OPMLark task",
                    info,
                    Schedule("weekend", "weekly", "10:30", days=("sat", "sun")),
                )
            )

        extra_day_xml = xml.replace("<Saturday/>", "<Monday/><Saturday/>")
        wrong_interval_xml = xml.replace("<WeeksInterval>1", "<WeeksInterval>2")
        for changed in (extra_day_xml, wrong_interval_xml):
            with self.subTest():
                result = type("Result", (), {"returncode": 0, "stdout": changed})()
                with patch("article_importer.scheduling.subprocess.run", return_value=result):
                    self.assertFalse(_windows_task_matches("OPMLark task", info, schedule))

    def test_cron_apply_returns_failed_changes_when_crontab_cannot_be_read(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            add_schedule_config(config, Schedule("evening", "daily", "19:00"))
            with (
                patch("article_importer.scheduling._platform", return_value="cron"),
                patch("article_importer.scheduling._read_crontab", side_effect=WorkspaceError("denied")),
            ):
                changes = apply_schedules(config)

            self.assertEqual(
                {"morning": ("failed", False), "evening": ("failed", False)},
                {item.id: (item.action, item.ok) for item in changes},
            )

    def test_cron_render_failure_keeps_the_previous_managed_line(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            schedule = Schedule("morning", "daily", "07:00")
            add_schedule_config(config, schedule)
            with (
                patch("article_importer.scheduling._platform", return_value="cron"),
                patch("article_importer.scheduling.shutil.which", return_value="/usr/bin/opmlark"),
            ):
                previous = cron_line(config, schedule, schedule_info(config, schedule))
            with (
                patch("article_importer.scheduling._platform", return_value="cron"),
                patch("article_importer.scheduling._read_crontab", return_value=previous + "\n"),
                patch("article_importer.scheduling.schedule_info", side_effect=WorkspaceError("missing executable")),
                patch("article_importer.scheduling._write_crontab") as write,
            ):
                changes = apply_schedules(config)

            self.assertFalse(changes[0].ok)
            write.assert_not_called()

    def test_removing_an_absent_windows_task_succeeds_without_executable(self) -> None:
        from article_importer.scheduling import remove_native_schedule

        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("missing", "daily", "07:00"))
            with (
                patch("article_importer.scheduling._platform", return_value="windows"),
                patch("article_importer.scheduling._windows_managed", return_value={}),
                patch("article_importer.scheduling.shutil.which", return_value=None),
            ):
                change = remove_native_schedule(config, "missing")

            self.assertTrue(change.ok)
            self.assertEqual("removed", change.action)

    def test_launchd_apply_replaces_managed_files_and_removes_stale(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = Path(initialize_workspace(root / "workspace")["config"])
            agents = root / "LaunchAgents"
            agents.mkdir()
            add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            with patch("article_importer.scheduling._platform", return_value="launchd"):
                with patch("article_importer.scheduling.shutil.which", return_value="/usr/local/bin/opmlark"):
                    morning = schedule_info(config, Schedule("morning", "daily", "07:00"))
            stale = agents / morning.name.replace(".morning", ".stale")
            stale = stale.with_suffix(stale.suffix + ".plist")
            stale.write_bytes(b"stale")

            with (
                patch("article_importer.scheduling._platform", return_value="launchd"),
                patch("article_importer.scheduling.shutil.which", return_value="/usr/local/bin/opmlark"),
                patch("article_importer.scheduling._launchd_directory", return_value=agents),
                patch("article_importer.scheduling._launchctl_reload") as reload,
                patch("article_importer.scheduling._launchctl_remove") as remove,
            ):
                changes = apply_schedules(config)

            self.assertTrue((agents / f"{morning.name}.plist").is_file())
            reload.assert_called_once()
            remove.assert_called_once()
            self.assertEqual({"morning": "created", "stale": "removed"}, {item.id: item.action for item in changes})

    def test_launchd_apply_reports_identical_plist_unchanged_without_reload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = Path(initialize_workspace(root / "workspace")["config"])
            agents = root / "LaunchAgents"
            agents.mkdir()
            schedule = Schedule("morning", "daily", "07:00")
            add_schedule_config(config, schedule)
            with (
                patch("article_importer.scheduling._platform", return_value="launchd"),
                patch("article_importer.scheduling.shutil.which", return_value="/usr/local/bin/opmlark"),
                patch("article_importer.scheduling._launchd_directory", return_value=agents),
            ):
                info = schedule_info(config, schedule)
                (agents / f"{info.name}.plist").write_bytes(launchd_plist(config, schedule, info))
                with patch("article_importer.scheduling._launchctl_reload") as reload:
                    changes = apply_schedules(config)

            self.assertEqual("unchanged", changes[0].action)
            reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
