from model import ammonia_cracker_model

result = ammonia_cracker_model(
    nh3_feed_kg_h=10,
    conversion_percent=98,
    heat_recovery_percent=60,
    h2_recovery_percent=95,
    temperature_c=650,
    pressure_bar=5
)

for key, value in result.items():
    if isinstance(value, float):
        print(key, ":", round(value, 3))
    else:
        print(key, ":", value)