from django.core.management.base import BaseCommand
from catalog.models import StorageZone, PhysicalBin, LogicalBin, BinMapping


class Command(BaseCommand):
    help = "Seed Garage Main zone with 48 physical bins, logical bins, and 1:1 mappings."

    def handle(self, *args, **options):
        try:
            zone = StorageZone.objects.get(code="GARAGE_MAIN")
        except StorageZone.DoesNotExist:
            self.stderr.write("Garage Main zone not found.")
            return

        self.stdout.write("Seeding PhysicalBins...")
        physical_bins = {}
        logical_number = 1

        for shelf in range(1, 7):      # Shelves 1–6
            for bin_num in range(1, 9):  # Bins 1–8
                pb, _ = PhysicalBin.objects.update_or_create(
                    zone=zone,
                    shelf_number=shelf,
                    bin_number=bin_num,
                )
                physical_bins[logical_number] = pb
                logical_number += 1

        self.stdout.write("Seeding LogicalBins...")
        for num in range(1, 49):
            LogicalBin.objects.update_or_create(
                zone=zone,
                number=num,
            )

        self.stdout.write("Seeding BinMappings...")
        for num in range(1, 49):
            lb = LogicalBin.objects.get(zone=zone, number=num)
            pb = physical_bins[num]

            BinMapping.objects.update_or_create(
                logical_bin=lb,
                defaults={"physical_bin": pb},
            )

        self.stdout.write(self.style.SUCCESS("Garage Main bins seeded successfully."))
