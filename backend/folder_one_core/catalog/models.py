from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class ActiveProductManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Product(models.Model):
    sku = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    brand = models.CharField(max_length=80, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    supplier_lead_time_days = models.PositiveIntegerField()
    attributes = models.JSONField(default=dict, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveProductManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["category", "is_deleted"])]

    def soft_delete(self):
        self.is_deleted, self.deleted_at = True, timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self):
        self.is_deleted, self.deleted_at = False, None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    @property
    def primary_image(self):
        imgs = list(self.images.all())
        primary = [i for i in imgs if i.is_primary]
        return (primary or imgs or [None])[0]

    def __str__(self):
        return f"{self.sku} {self.name}"


def product_image_path(instance, filename):
    return f"products/{instance.product.sku}/{filename}"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=product_image_path)
    is_primary = models.BooleanField(default=False)
    alt_text = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "id"]
