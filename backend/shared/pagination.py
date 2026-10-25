from rest_framework.pagination import PageNumberPagination

from config.loader import business


class ConfigPagination(PageNumberPagination):
    page_size = business()["api"]["page_size"]
    max_page_size = business()["api"]["max_page_size"]
    page_size_query_param = "page_size"
