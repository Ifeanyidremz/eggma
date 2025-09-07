# from django.shortcuts import render,HttpResponse
# from django.contrib.auth.decorators import login_required
# from django.utils.decorators import method_decorator
# from django.views.generic import View

# # Create your views here.




# @method_decorator(login_required, name='dispatch')
# class DashboardView(View):
#     template_name = 'profile.html'
    
#     def get(self, request):
#         # You can add user-specific data here
#         context = {
#             'user': request.user,
#             # Add any dashboard-specific data
#             'total_earnings': 1247.50,  # Replace with actual data
#             'accuracy_rate': 73,       # Replace with actual data
#             'total_xp': 2450,          # Replace with actual data
#             'active_predictions': 47,   # Replace with actual data
#         }
#         return render(request, self.template_name, context)