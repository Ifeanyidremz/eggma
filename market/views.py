from django.shortcuts import render,HttpResponse




def marketPage(request):

    return render(request, 'market_list.html')
