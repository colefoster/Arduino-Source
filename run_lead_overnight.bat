@echo off
cd C:\Dev\pokemon-champions
set PYTHONUNBUFFERED=1

echo === Lead Advisor Training: min_rating=1400 ===
python -m src.vgc_model.training.train_lead --epochs 100 --min-rating 1400 --patience 15 --run-id lead_1400

echo === Lead Advisor Training: min_rating=1200 ===
python -m src.vgc_model.training.train_lead --epochs 100 --min-rating 1200 --patience 15 --run-id lead_1200

echo === Lead Advisor Training: min_rating=1000 ===
python -m src.vgc_model.training.train_lead --epochs 100 --min-rating 1000 --patience 15 --run-id lead_1000

echo === All runs complete ===
