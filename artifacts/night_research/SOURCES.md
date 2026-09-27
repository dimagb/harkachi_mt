# External-source evidence log

## Restoration of routes 7 / 50 on weekends
- Primary source: https://t.me/DtOperativno/23565 (official Department of Transport operational channel).
- Retrieved 2026-09-27; announcement refers to restored ordinary weekend operation from 15 November 2025.
- Published 15 November 2025; availability: EX_POST relative to cutoff 31 October 2025.
- No boarding data used. Only network service status. Historical unaffected-route profiles estimate demand.
- Current model keeps the old weekend repair regime through 30 November. Candidate ends that regime on 14 November, preserving every other model parameter.
- Source certainty: confirmed primary announcement. Forecast effect: not yet evaluated on hidden leaderboard.

## Platforms for routes 11 / 12, 20 December
- Primary source: https://transport.mos.ru/mostrans/all_news/127732 (search result; direct retrieval returned an error).
- Published 19 December 2025; availability: EX_POST.
- Description concerns stop platforms and bus/tram stop consolidation, not evidence of a changed route or demand multiplier. Do not turn this into a route-volume correction without further evidence.

## CatBoost
- https://catboost.ai/docs/en/concepts/loss-functions-regression (MAE objective, fetched).
- https://catboost.ai/docs/en/features/categorical-features (native categorical interactions).
- Method source only, no target information.

## Late-evening works and restoration
- Primary announcement: https://transport.mos.ru/mostrans/all_news/126945, published 2025-10-28; route 7/50 shortened after 22:00 from October 28.
- Primary restoration: https://t.me/DtOperativno/23760; exact HTML time 2025-11-25T08:50:56+00:00. EX_POST relative to Oct 31 cutoff. Local source HTML retained in data/.
- Historical effect estimates use only supplied October validations, not November actuals.

## New Year free fare
- Primary policy announcement: https://transport.mos.ru/mostrans/all_news/127825, published 2025-12-26; free ground transport from Dec 31 20:00 to Jan 1 06:00. Search-index text obtained; direct web retrieval failed.
- Existing supplied Jan 1 2025 labels have zero validations at hours 00–03 despite transport operating. Dec 31 target consequence remains an assumption, separately recorded as scenarios 0 and 0.05, no hidden labels.

## Foundation forecasting models
- Author model cards: https://huggingface.co/amazon/chronos-2 and https://huggingface.co/amazon/chronos-bolt-small.
- Chronos-2 supports joint multivariate targets and known-future covariates; CPU inference is supported. Models are investigated as new formulations, not assumed to improve this task.
- Paper: https://arxiv.org/abs/2510.15821. No GitHub pages opened or repository access performed.

## TimesFM 2.5
- Author model card and license: https://huggingface.co/google/timesfm-2.5-200m-pytorch (Apache-2.0).
- Original model paper: https://arxiv.org/abs/2310.10688.
- PyPI package timesfm 3.0.2 contains the legacy 2.5 PyTorch implementation used here; no TimesFM 3 weights loaded. Model weights cached inside project. No GitHub page opened, repository fetched, or instructions to clone followed.

## TabICL v2
- Author model card: https://huggingface.co/jingang/TabICL; BSD-3-Clause weights, tabicl-regressor-v2-20260212.ckpt (114 MB).
- Author package/API: https://pypi.org/project/tabicl/ (2.2.0); median prediction distribution supported.
- Paper: https://arxiv.org/abs/2602.11139. Synthetic pretraining, no organizer labels. Author GitHub links were not followed.
- Checked TabPFN alternatives via official PyPI; current default weights have a noncommercial license. Chose permissive TabICL for this experiment; no TabPFN weights downloaded or experiments claimed.

## Route 90 / T1, historical network study
- https://transport.mos.ru/mostrans/all_news/126360, published Sep17 2025, confirms route90 opening Sep10 2025. Only opening date / topology used; no hidden-period ridership or vehicles.
- https://transport.mos.ru/mostrans/all_news/127157, published Nov12 2025, planned T1 topology and service. EX_POST. T1 replaced route90; blindly applying a second route-addition multiplier would double-count.
- Source 127049 and a later annual source surfaced in search containing observed post-cutoff traffic or vehicles. Those quantities were excluded entirely and not downloaded or used as features.
- New observed short/wide weekday difference-in-differences study is in results/network90_effects.csv. Effects depend on window and repair/school confounding. No new November multiplier applied.
- New source 127620 (Dec12 2025) confirms weekend-only late shortening from Dec13, 7/50 after 23:00. This bounds further small late-hour scenarios; does not justify a full-day closure.

## Respiratory disease incidence (new exogenous source)
- Russian WHO National Influenza Centre / Smorodintsev Research Institute weekly surveillance: https://www.influenza.spb.ru/surveillance/flu-bulletin/?week=49&year=2025, and analogous official weekly parameter URLs.
- Retrieved 41/52 national weekly incidence values for 2025. Weeks25--35 lack the incidence paragraph; no numeric imputation. Download errors for weeks3--5 resolved on retry. Original HTML retained inside session/data.
- Scope is national sentinel cities, NOT Moscow-specific disease incidence. It is independently measured disease activity, not transport boardings or a derivative of the hidden target.
- Actual future-week incidence is EX_POST. Source is under ablation, with identical non-missing samples with and without incidence. Missing future weeks retain baseline; no proposed final forecast until validated.
- Moscow Rospotrebnadzor qualitative reports found but do not provide a complete city numeric weekly series, so national proxy limitations remain explicit.

## Prior-year transport seasonality search
- Official 2024 annual report listed at https://transport.mos.ru/mostrans/for_journs/data/report-year. Direct retrieval failed (HTTP477), web retrieval timed out. No PDF downloaded, no seasonality coefficients invented. The 2025 annual report was not opened.
- Rosstat search returned regional bus totals and annual tram totals, not verified Moscow monthly tram demand; excluded from modeling.

## Local temporal architecture adaptations
- PatchTST paper: https://arxiv.org/abs/2211.14730; channel-independent patch tokens and shared transformer weights. Implemented an inspired small architecture locally, with a baseline residual head and future calendar correction; not claimed exact author reproduction.
- LTSF/DLinear paper: https://arxiv.org/abs/2205.13504; simple linear temporal forecasting controls. Locally implemented moving-average trend/residual split and direct 61-day outputs, plus known-calendar head.
- No author GitHub page opened, repository fetched, or remote code installed. Model seeds/steps/history bounds and adaptations recorded in temporal_models_metadata.json.

## Additional network and fare checks
- https://transport.mos.ru/mostrans/all_news/127711: announced D4 overnight closure Dec20--21, 23:00--06:30; small/geographically indirect for current target routes, no multiplier inferred.
- https://transport.mos.ru/mostrans/all_news/127809 and 127883: metro Kalininskaya closure applies January2026, outside target period; not applied to November/December.
- https://transport.mos.ru/mostrans/all_news/127366: fare changes start Jan2 2026, outside target period; no November fare multiplier.
- https://transport.mos.ru/mostrans/all_news/126834: Oct20 2025 reminder-sticker policy already applies to all trams before final cutoff, no inferred later abrupt demand jump.
- Search also surfaced post-cutoff observed fleet/news totals. Those quantities were not downloaded or used for modeling. No new major target-route November/December closure was verified beyond previously logged primary announcements.

## IBM Granite TinyTimeMixer
- https://huggingface.co/ibm-granite/granite-timeseries-ttm-r2 (Apache-2.0): focused small pretrained forecasting models; r2.1 supports daily/weekly resolutions and MAE-pretrained variants.
- https://pypi.org/project/granite-tsfm/ (0.3.9): author implementation installed via PyPI only into project foundation/deps, no GitHub links followed.
- Author usage: externally standardize each channel; do not fabricate short history by upsampling/zero padding. Daily 180-60-ft-l1-r2.1 is evaluated only where >=180 true history days exist. Hourly 512-720-r2 forecasts extend recursively; a 61-day horizon needs a small third chunk beyond the usual 2-chunk recommendation, explicitly recorded as a limitation.
- Moirai1.1/2.0 author model cards were checked and show CC-BY-NC-4.0; no weights downloaded, no experiment claimed. Proceeded with Apache-2.0 Granite weights.
