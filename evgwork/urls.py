from django.contrib import admin
from django.urls import path,include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('acounts.urls')),
    path('market/', include('market.urls')),
    path('predicz/', include('predict.urls')),
]
