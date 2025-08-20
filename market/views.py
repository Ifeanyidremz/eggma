from django.shortcuts import render,HttpResponse




def marketPage(request):

    return render(request, 'market_list.html')




def marketDetail(request):

    return render(request,'market_detail.html')




def userPortfolio(request):

    return render(request, 'portfolio.html')
