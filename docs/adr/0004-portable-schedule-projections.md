# Treat native schedules as projections of workspace configuration

OPMLark stores named daily, weekly, monthly, and one-time schedules in `config.toml`. The CLI and TUI edit that portable intent, while `schedule apply` projects enabled entries into Windows Task Scheduler, per-user macOS launchd agents, or the Linux user crontab.

Raw cron is not part of the public model because valid cron expressions do not always translate faithfully to the other operating systems. Native artifacts include a workspace digest and schedule ID, allowing OPMLark to reconcile its own entries without changing unrelated jobs. This trades access to every backend-specific feature for portability, inspectable configuration, and repeatable repair after moving or reinstalling a workspace.
