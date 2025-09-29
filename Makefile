.PHONY: install check-env ingest extract retrospective hearing collect build_agenda post_agenda day_of two_days_before daily day_before test_slack

install:
	pip install -r requirements.txt

check-env:
	@test -f .env || (echo "[Makefile] .env not found. Copy .env.example to .env and fill values." && exit 1)

ingest: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.docs_ingest'

extract: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.action_extract'

retrospective: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.post_retrospective'

hearing: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.post_hearing'

collect: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.collect_replies'

build_agenda: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.build_agenda'

post_agenda: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.post_agenda'

# Combined flows
day_of: ingest extract retrospective

two_days_before: hearing

daily: collect

day_before: build_agenda post_agenda

test_slack: check-env
	bash -lc 'set -a; source .env; set +a; python -m src.test_slack $$CHANNEL $$MESSAGE'
