# Local cleanup candidates

The following ignored local artifacts were deliberately left untouched because they may contain
private data or useful recovery material: `.env`, `media/`, `private_media/`, local database dumps,
and backups. Review and remove them from future source archives manually. Generated `htmlcov/`,
`.coverage`, `coverage.xml`, caches, and bytecode are ignored and may be regenerated safely.
