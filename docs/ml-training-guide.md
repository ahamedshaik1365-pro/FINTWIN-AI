# ML training guide

## Supplied data

`public/datasets/` contains the CSV files from the supplied archive, plus its data dictionary. The archive explicitly describes these 500 fictional user records and related histories as synthetic, designed for demos and prototyping. It is not a survey or ground truth about real Indian employees. The provided Python generator/loader scripts are retained only in the extracted scratch archive under `work/source-datasets`; they are not executed by the application.

The ML Studio **Use the supplied synthetic FinTwin sample** button uploads `users.csv` to the account you connect. It defaults to `risk_flag_12m` classification. The default feature selection excludes user identifiers, names, exact city/age fields, and the known future-outcome columns (`had_layoff_in_year`, `min_savings_12m`, `savings_12m_actual`, and `risk_flag_12m`). Check the selected feature list before training another target.

## Workflow

1. Start the backend, complete the initial Alembic migration, and register or sign in to a local account in ML Studio.
2. Upload a CSV or Excel dataset, up to 20 MB and 250,000 rows. Inspect the checksum, types, missing values, duplicate rows, and warnings.
3. Select a numeric regression or categorical classification target and pre-outcome features. The API requires at least 30 labelled rows; classification requires at least five rows per class.
4. The current trainer runs a deterministic stratified 70/15/15 train/validation/test split (random seeds 42 and 43). It fits imputers and one-hot encoding only within each candidate pipeline's training partition.
5. A Dummy baseline and Random Forest candidate are evaluated on validation data. The better validation model is evaluated once on the held-out test split, and only measured metrics are reported.
6. The resulting model stays pending approval. Activating it is an explicit account-owner action. Prediction inputs must match the registered schema exactly.

The API trainer currently runs synchronously and is for modest local datasets. Do not train files over 50,000 rows until a durable background job queue is configured. Test metrics on synthetic data measure only fit to that generated process; they do not establish real-world predictive performance or financial advice quality.

## One measured wiring check

The included API test trained `risk_flag_12m` on the supplied 500-row synthetic users file, with 75 held-out test rows. For that seeded split, the Random Forest scored accuracy **0.893**, macro precision **0.867**, macro recall **0.683**, and macro F1 **0.732**. The dummy baseline accuracy was **0.773**. This is a reproducible pipeline check on fictional, hand-designed records, not an accuracy claim about real people. The test also verifies approval, prediction, and owner isolation.
