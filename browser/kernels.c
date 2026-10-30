/* Browser numerical kernels. Equations and event boundaries follow plant.py,
 * fast_integrator.py and tuning_simulator.py. IEEE double, no fast math. */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define MAXN 14
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
static double ld[31],cd[121];
void k_curves(const double *l,const double *c){memcpy(ld,l,sizeof(ld));memcpy(cd,c,sizeof(cd));}
static double interp(double x,const double *v,int n,double step){
 if(isnan(x))return NAN;
 if(x<=0)return v[0];if(x>=step*(n-1))return v[n-1];
 int j=(int)floor(x/step);return v[j]+(x-j*step)*(v[j+1]-v[j])/step;
}
double k_l(double i,const double *p){return p[28]>=.5?interp(fabs(i),ld,31,1.)*p[1]:p[39];}
double k_c(double v,const double *p){return p[29]>=.5?(.00094+2*interp(fabs(v),cd,121,.5))*p[2]:p[40];}
double k_iph(double t,const double *p){
 if(p[38]==0||t<p[36])return p[8];if(p[38]==1||p[37]<=0)return p[35];
 double a=MIN(1.,MAX(0.,(t-p[36])/p[37]));return p[8]+a*(p[35]-p[8]);
}
double k_ipv(double v,double t,const double *p){return k_iph(t,p)-p[9]*expm1(MIN(100.,v/p[10]));}
void k_nodes(double t,const double *y,const double *p,int on,int conducting,double *a){
 double il=on||conducting?y[1]:0.;
 if(p[34]==0){double ip=k_ipv(y[0],t,p),ib=(y[2]-p[6])/p[5];
  double z[15]={y[0],ip,y[0],y[0],y[2],y[2],y[2],ib,ib,0.,ip-(on?il:0.),il-ib,0.,0.,il};memcpy(a,z,sizeof(z));return;}
 double aa=1+p[15]*p[30],b=p[13]*aa+p[15],target=y[0]-p[15]*y[8];
 double vp=(target+b*k_iph(t,p))/aa;
 for(int j=0;j<12;j++){double ex=exp(MIN(100.,vp/p[10])),ip=k_iph(t,p)-p[9]*(ex-1);
  double delta=(aa*vp-b*ip-target)/(aa+b*p[9]*ex/p[10]);vp-=delta;if(fabs(delta)<1e-12)break;}
 double ip=k_ipv(vp,t,p),vf=vp-p[13]*ip,icpv=ip-y[8]-p[30]*vf;
 double vi=(y[7]+p[16]*(y[8]-(on?il:0.)))/(1+p[16]*p[31]);
 double icin=y[8]-(on?il:0.)-p[31]*vi;
 double gc=1/p[17],gpr=1/p[18],gf=1/p[19],gcp=1/p[21],gb=1/p[5],ga=1/(p[23]+p[24]),graw=gb+gf+ga;
 double av=gc+gpr+p[32],bv=il+gc*y[2],ap=gcp+gpr+gf+p[33]-gf*gf/graw;
 double bp=gcp*y[9]+gf*(gb*p[6]+ga*y[10])/graw,vplus=(bp+gpr*bv/av)/(ap-gpr*gpr/av);
 double vo=(bv+gpr*vplus)/av,vraw=(gb*p[6]+gf*vplus+ga*y[10])/graw;
 double iout=(vo-vplus)*gpr,ib=(vraw-p[6])*gb,ico=(vo-y[2])*gc,icp=(vplus-y[9])*gcp,ica=(vraw-y[10])*ga;
 double z[15]={vp,ip,vf,vi,vo,vplus,vraw,iout,ib,icpv,icin,ico,icp,ica,il};memcpy(a,z,sizeof(z));
}
void k_rhs(double t,const double *y,int n,const double *p,int on,int conducting,double *o){
 double a[15];k_nodes(t,y,p,on,conducting,a);memset(o,0,n*sizeof(double));
 double vp=a[0],ip=a[1],vf=a[2],vi=a[3],vo=a[4],vplus=a[5],vraw=a[6],iout=a[7],ib=a[8];
 double icpv=a[9],icin=a[10],ico=a[11],icp=a[12],ica=a[13],il=a[14],ind,loss;
 if(p[34]==0){o[0]=icin/p[0];o[2]=ico/p[40];ind=p[39];loss=p[5]*ib*ib;}
 else{o[0]=icpv/p[14];o[7]=icin/p[0];o[8]=(vf-vi-p[12]*y[8])/p[11];
  o[2]=ico/k_c(y[2],p);o[9]=icp/p[20];o[10]=ica/p[22];ind=k_l(il,p);
  double if3=(vplus-vraw)/p[19];
  loss=p[13]*ip*ip+p[12]*y[8]*y[8]+p[15]*icpv*icpv+p[16]*icin*icin+p[17]*ico*ico+p[18]*iout*iout+
   p[19]*if3*if3+p[21]*icp*icp+(p[23]+p[24])*ica*ica+p[5]*ib*ib+p[30]*vf*vf+p[31]*vi*vi+p[32]*vo*vo+p[33]*vplus*vplus;}
 if(on){o[1]=(vi-vo-(p[3]+p[4])*il)/ind;loss+=(p[3]+p[4])*il*il;}
 else if(conducting){double rd=p[34]?p[26]:0.;o[1]=(-vo-p[25]-(p[3]+rd)*il)/ind;loss+=(p[3]+rd)*il*il+p[25]*il;}
 o[3]=p[7]>0?(vf-y[3])/p[7]:0.;o[4]=vp*ip;o[5]=p[6]*ib;o[6]=loss;
 if(n>7){o[11]=p[27]>0?(il-y[11])/p[27]:0.;o[12]=p[27]>0?(y[8]-y[12])/p[27]:0.;o[13]=p[7]>0?(vo-y[13])/p[7]:0.;}
}
void k_record(double t,const double *y,int n,const double *p,int on,int conducting,double *v){
 double a[15];k_nodes(t,y,p,on,conducting,a);double il=a[14],terminal=0.,vl=0.;
 if(on)terminal=a[3]-p[4]*il-a[4];else if(conducting)terminal=-p[25]-(p[34]?p[26]:0.)*il-a[4];
 if(on||conducting)vl=terminal-p[3]*il;
 v[0]=a[0];v[1]=a[1];v[2]=a[2];v[3]=p[34]?y[8]:NAN;v[4]=vl;v[5]=terminal;v[6]=a[3];v[7]=a[4];v[8]=a[5];v[9]=y[1];
 v[10]=p[7]>0?y[3]:a[2];v[11]=p[27]>0&&n>7?y[11]:y[1];
 v[12]=p[27]>0&&n>7?y[12]:(p[34]?y[8]:a[1]);v[13]=p[7]>0&&n>7?y[13]:a[4];v[14]=a[0]*a[1];
}
void k_records(const double *times,const double *states,int count,int n,const double *p,int on,int conducting,double duty,int averaged,double *out){
 for(int i=0;i<count;i++){double a[15],b[15];
  if(averaged){k_record(times[i],states+i*n,n,p,1,1,a);k_record(times[i],states+i*n,n,p,0,1,b);for(int j=0;j<15;j++)out[i*15+j]=duty*a[j]+(1-duty)*b[j];}
  else k_record(times[i],states+i*n,n,p,on,conducting,out+i*15);}
}
static const double A[7][7]={{0},{1./5},{3./40,9./40},{44./45,-56./15,32./9},
 {19372./6561,-25360./2187,64448./6561,-212./729},{9017./3168,-355./33,46732./5247,49./176,-5103./18656},
 {35./384,0,500./1113,125./192,-2187./6784,11./84}};
static const double B[7]={35./384,0,500./1113,125./192,-2187./6784,11./84,0};
static const double E[7]={35./384-5179./57600,0,500./1113-7571./16695,125./192-393./640,-2187./6784+92097./339200,11./84-187./2100,-1./40};
static const double T[7]={0,1./5,3./10,4./5,8./9,1,1};
static void rk(double t,const double *y,int n,double h,const double *p,int on,int cond,double *trial,double *err){
 double k[7][MAXN],stage[MAXN];
 for(int r=0;r<7;r++){for(int j=0;j<n;j++){double s=0.;for(int a=0;a<r;a++)s+=A[r][a]*k[a][j];stage[j]=y[j]+h*s;}k_rhs(t+T[r]*h,stage,n,p,on,cond,k[r]);}
 for(int j=0;j<n;j++){trial[j]=y[j];err[j]=0.;for(int r=0;r<7;r++){trial[j]+=h*B[r]*k[r][j];err[j]+=h*E[r]*k[r][j];}}
}
static void legacy_rhs(const double *y,const double *p,int on,int cond,double *o){
 double v=y[0],i=y[1],vo=y[2],vs=y[3],ip=p[8]-p[9]*expm1(MIN(100.,v/p[10])),ib=(vo-p[6])/p[5],di,ii,loss;
 if(on){di=(v-vo-(p[3]+p[4])*i)/p[1];ii=i;loss=(p[3]+p[4])*i*i;}
 else if(cond){di=(-vo-.7-p[3]*i)/p[1];ii=0.;loss=p[3]*i*i+.7*i;}
 else{di=0.;ii=0.;i=0.;loss=0.;}
 o[0]=(ip-ii)/p[0];o[1]=di;o[2]=(i-ib)/p[2];o[3]=p[7]>0?(v-vs)/p[7]:0.;o[4]=v*ip;o[5]=p[6]*ib;o[6]=loss+p[5]*ib*ib;
}
static void legacy_step(const double *y,double h,const double *p,int on,int cond,double *trial,double *err){
 double k[7][7],s[7];legacy_rhs(y,p,on,cond,k[0]);
 for(int j=0;j<7;j++)s[j]=y[j]+h*k[0][j]/5;legacy_rhs(s,p,on,cond,k[1]);
 for(int j=0;j<7;j++)s[j]=y[j]+h*(3./40*k[0][j]+9./40*k[1][j]);legacy_rhs(s,p,on,cond,k[2]);
 for(int j=0;j<7;j++)s[j]=y[j]+h*(44./45*k[0][j]-56./15*k[1][j]+32./9*k[2][j]);legacy_rhs(s,p,on,cond,k[3]);
 for(int j=0;j<7;j++)s[j]=y[j]+h*(19372./6561*k[0][j]-25360./2187*k[1][j]+64448./6561*k[2][j]-212./729*k[3][j]);legacy_rhs(s,p,on,cond,k[4]);
 for(int j=0;j<7;j++)s[j]=y[j]+h*(9017./3168*k[0][j]-355./33*k[1][j]+46732./5247*k[2][j]+49./176*k[3][j]-5103./18656*k[4][j]);legacy_rhs(s,p,on,cond,k[5]);
 for(int j=0;j<7;j++)trial[j]=y[j]+h*(35./384*k[0][j]+500./1113*k[2][j]+125./192*k[3][j]-2187./6784*k[4][j]+11./84*k[5][j]);legacy_rhs(trial,p,on,cond,k[6]);
 for(int j=0;j<7;j++)err[j]=h*(E[0]*k[0][j]+E[2]*k[2][j]+E[3]*k[3][j]+E[4]*k[4][j]+E[5]*k[5][j]-1./40*k[6][j]);
}
static double *rtimes=NULL,*rstates=NULL;static int cap=0,rn=0,rs=0,rf=0,rc=0,rnstate=0;
static int reserve(int count,int n){if(count<=cap&&n==rnstate)return 1;int nc=MAX(128,cap);while(count>nc)nc*=2;
 double *nt=malloc(nc*sizeof(double)),*ns=malloc(nc*n*sizeof(double));if(!nt||!ns){free(nt);free(ns);return 0;}
 if(rn&&rtimes){memcpy(nt,rtimes,rn*sizeof(double));if(n==rnstate)memcpy(ns,rstates,rn*n*sizeof(double));}
 free(rtimes);free(rstates);rtimes=nt;rstates=ns;cap=nc;rnstate=n;return 1;}
static int begin_result(double t,const double *y,int n){rn=rs=rf=rc=0;if(!reserve(1,n)){rc=-1;return 0;}rtimes[0]=t;memcpy(rstates,y,n*sizeof(double));rn=1;return 1;}
static int append_result(double t,const double *y,int n){if(!reserve(rn+1,n)){rc=-1;return 0;}rtimes[rn]=t;memcpy(rstates+rn*n,y,n*sizeof(double));rn++;rs++;return 1;}
int k_result_count(void){return rn;}int k_result_steps(void){return rs;}int k_result_nfev(void){return rf;}int k_result_code(void){return rc;}
double *k_result_times(void){return rtimes;}double *k_result_states(void){return rstates;}
static int event(const double *y,const double *p,int on,int cond,int *ix,double *level,int *up){
 *ix=0;*level=.1;*up=0;if(y[0]<=.1)return 3;
 double imax=p[34]&&p[28]>=.5?30.:60.;*ix=1;*level=imax;*up=1;if(y[1]>=imax)return 4;
 *ix=2;*level=60.;if(p[34]&&p[29]>=.5&&y[2]>=60)return 5;
 *ix=1;*level=-.01;*up=0;if(on&&y[1]<=-.01)return 2;*level=0.;if(!on&&cond&&y[1]<=0)return 1;
 *ix=0;*level=0.;return 0;
}
void k_integrate(double t,double end,const double *initial,int n,const double *p,int on,int cond,double maxstep,double tol){
 if(!begin_result(t,initial,n))return;double y[MAXN],trial[MAXN],err[MAXN],h=MIN(maxstep,end-t);memcpy(y,initial,n*sizeof(double));int ix,up;double level;
 rc=event(y,p,on,cond,&ix,&level,&up);if(rc)return;
 for(int attempt=0;attempt<200000;attempt++){
  if(t>=end){rc=0;return;}double m=MAX(fabs(t),fabs(end)),spacing=nextafter(m,INFINITY)-m;
  if(end-t<=8*spacing){rtimes[rn-1]=end;rc=0;return;}
  h=MIN(h,MIN(maxstep,end-t));if(h<=1e-16||t+h==t)break;
  rk(t,y,n,h,p,on,cond,trial,err);rf+=7;double norm=0.;
  for(int j=0;j<n;j++){double atol=j>=4&&j<=6?1e-10:1e-8;double e=err[j]/(atol+tol*MAX(fabs(y[j]),fabs(trial[j])));norm+=e*e;if(!isfinite(trial[j]))norm=INFINITY;}
  norm=sqrt(norm/n);if(norm>1||!isfinite(norm)){h*=isfinite(norm)?MAX(.1,.9*pow(norm,-.2)):.1;continue;}
  rc=event(trial,p,on,cond,&ix,&level,&up);
  if(rc){double lo=0.,hi=h,z[MAXN],ze[MAXN];for(int j=0;j<50;j++){double mid=(lo+hi)/2;rk(t,y,n,mid,p,on,cond,z,ze);rf+=7;
    if(up?z[ix]>=level:z[ix]<=level)hi=mid;else lo=mid;if(hi-lo<5e-14)break;}
   h=(lo+hi)/2;rk(t,y,n,h,p,on,cond,trial,err);rf+=7;trial[ix]=level;}
  t=!rc&&end-t<=h?end:t+h;memcpy(y,trial,n*sizeof(double));if(!append_result(t,y,n))return;if(rc)return;
  h*=norm==0?5.:MIN(5.,MAX(.2,.9*pow(norm,-.2)));
 }rc=-1;
}
static double legacy_root(const double *y,double h,const double *p,int on,int cond,int ix,double level,int up){
 double lo=0.,hi=h,z[7],e[7];for(int j=0;j<60;j++){double mid=(lo+hi)*.5;legacy_step(y,mid,p,on,cond,z,e);rf+=7;
  if(up?z[ix]>=level:z[ix]<=level)hi=mid;else lo=mid;if(hi-lo<=5e-14)break;}return(lo+hi)*.5;
}
void k_legacy_integrate(double t,double end,const double *initial,const double *p,int on,int cond,double maxstep,double tol){
 if(!begin_result(t,initial,7))return;double y[7],z[7],err[7],h=MIN(end-t,maxstep);memcpy(y,initial,sizeof(y));
 if(y[0]<=.1){rc=3;return;}if(y[1]>=60){rc=4;return;}if(on&&y[1]<=-.01){rc=2;return;}if(!on&&cond&&y[1]<=0){rstates[1]=0;rc=1;return;}
 const double atol[7]={1e-8,1e-9,1e-8,1e-8,1e-10,1e-10,1e-10};int attempts=0;
 while(t<end){if(++attempts>20000||rs>=10000){rc=-1;return;}double remaining=end-t;h=MIN(h,MIN(maxstep,remaining));
  if(h<=0||t+h==t){rc=-1;return;}legacy_step(y,h,p,on,cond,z,err);rf+=7;double norm=0.;
  for(int j=0;j<7;j++){double e=err[j]/(atol[j]+tol*MAX(fabs(y[j]),fabs(z[j])));norm+=e*e;if(!isfinite(z[j]))norm=INFINITY;}norm=sqrt(norm/7);
  if(!isfinite(norm)||norm>1){h*=isfinite(norm)?MAX(.1,.9*pow(norm,-.2)):.1;continue;}
  rc=0;double first=h,root;if(z[0]<=.1){root=legacy_root(y,h,p,on,cond,0,.1,0);if(root<=first){first=root;rc=3;}}
  if(rc){legacy_step(y,h,p,on,cond,z,err);rf+=7;}
  if(z[1]>=60){root=legacy_root(y,h,p,on,cond,1,60.,1);if(root<=first){first=root;rc=4;}legacy_step(y,h,p,on,cond,z,err);rf+=7;}
  double threshold=on?-.01:0.;if((on||cond)&&z[1]<=threshold){root=legacy_root(y,h,p,on,cond,1,threshold,0);if(root<=first){first=root;rc=on?2:1;}}
  if(rc){legacy_step(y,first,p,on,cond,z,err);rf+=7;if(rc==1)z[1]=0.;else if(rc==2)z[1]=-.01;else if(rc==3)z[0]=.1;else z[1]=60.;h=first;}
  double next=!rc&&h>=remaining?end:t+h;if(next<=t){rc=-1;return;}t=next;memcpy(y,z,sizeof(y));if(!append_result(t,y,7))return;if(rc)return;
  h*=norm==0?5.:MIN(5.,MAX(.2,.9*pow(norm,-.2)));
 }rc=0;
}
void k_average_rhs(double t,const double *y,int n,const double *p,double duty,double *out){
 double a[MAXN],b[MAXN];k_rhs(t,y,n,p,1,1,a);k_rhs(t,y,n,p,0,1,b);for(int i=0;i<n;i++)out[i]=duty*a[i]+(1-duty)*b[i];
}
void k_jacobian(double t,const double *y,int n,const double *p,double duty,double *a){
 memset(a,0,n*n*sizeof(double));for(int j=0;j<n;j++){if(j>=4&&j<=6)continue;double h=MAX(1.,fabs(y[j]))*1e-6,yp[MAXN],ym[MAXN],fp[MAXN],fm[MAXN];
  memcpy(yp,y,n*sizeof(double));memcpy(ym,y,n*sizeof(double));yp[j]+=h;ym[j]-=h;k_average_rhs(t,yp,n,p,duty,fp);k_average_rhs(t,ym,n,p,duty,fm);for(int i=0;i<n;i++)a[i*n+j]=(fp[i]-fm[i])/(2*h);}
}
static int inverse_matrix(const double *jac,int n,double h,double *out){
 double a[MAXN][MAXN*2],gamma=1-1/sqrt(2.);
 for(int i=0;i<n;i++)for(int j=0;j<n;j++){a[i][j]=(i==j?1.:0.)-gamma*h*jac[i*n+j];a[i][n+j]=i==j?1.:0.;}
 for(int k=0;k<n;k++){int pivot=k;for(int i=k+1;i<n;i++)if(fabs(a[i][k])>fabs(a[pivot][k]))pivot=i;if(!isfinite(a[pivot][k])||a[pivot][k]==0)return 0;
  if(pivot!=k)for(int j=0;j<2*n;j++){double z=a[k][j];a[k][j]=a[pivot][j];a[pivot][j]=z;}
  double v=a[k][k];for(int j=0;j<2*n;j++)a[k][j]/=v;
  for(int i=0;i<n;i++)if(i!=k){v=a[i][k];for(int j=0;j<2*n;j++)a[i][j]-=v*a[k][j];}}
 for(int i=0;i<n;i++)for(int j=0;j<n;j++)out[i*n+j]=a[i][n+j];return 1;
}
int k_sdirk(double t,const double *y,int n,double h,const double *p,double duty,const double *inverse,double *stage){
 double gamma=1-1/sqrt(2.),f[MAXN],res[MAXN],delta[MAXN],k1[MAXN],base[MAXN];memcpy(stage,y,n*sizeof(double));
 for(int it=0;it<7;it++){k_average_rhs(t+gamma*h,stage,n,p,duty,f);for(int j=0;j<n;j++)res[j]=stage[j]-y[j]-gamma*h*f[j];
  for(int i=0;i<n;i++){delta[i]=0;for(int j=0;j<n;j++)delta[i]+=inverse[i*n+j]*(-res[j]);stage[i]+=delta[i];}
  double error=0.;for(int j=0;j<n;j++){double v=fabs(delta[j])/(1+fabs(stage[j]));error=isfinite(v)?MAX(error,v):INFINITY;}if(error<1e-10)break;}
 k_average_rhs(t+gamma*h,stage,n,p,duty,k1);for(int j=0;j<n;j++){base[j]=y[j]+(1-gamma)*h*k1[j];stage[j]=base[j]+gamma*h*k1[j];}
 for(int it=0;it<7;it++){k_average_rhs(t+h,stage,n,p,duty,f);for(int j=0;j<n;j++)res[j]=stage[j]-base[j]-gamma*h*f[j];
  for(int i=0;i<n;i++){delta[i]=0;for(int j=0;j<n;j++)delta[i]+=inverse[i*n+j]*(-res[j]);stage[i]+=delta[i];}
  double error=0.;for(int j=0;j<n;j++){double v=fabs(delta[j])/(1+fabs(stage[j]));error=isfinite(v)?MAX(error,v):INFINITY;}if(error<1e-10)break;}
 k_average_rhs(t+h,stage,n,p,duty,f);double error=0.;for(int j=0;j<n;j++){double v=fabs(stage[j]-base[j]-gamma*h*f[j])/(1+fabs(stage[j]));error=isfinite(v)?MAX(error,v):INFINITY;}return error<1e-8;
}
void k_average_integrate(double t,double end,const double *initial,int n,const double *p,double duty,double tol,double maxstep,double *jac){
 if(!begin_result(t,initial,n))return;double y[MAXN],whole[MAXN],half[MAXN],fine[MAXN],inv[MAXN*MAXN],invhalf[MAXN*MAXN];memcpy(y,initial,n*sizeof(double));double h=MIN(maxstep,end-t);int attempts=0;
 while(t<end-1e-14&&attempts<100000){h=MIN(h,end-t);attempts++;
  int ok=inverse_matrix(jac,n,h,inv)&&inverse_matrix(jac,n,h*.5,invhalf);int a=0,b=0,c=0;
  if(ok){a=k_sdirk(t,y,n,h,p,duty,inv,whole);b=k_sdirk(t,y,n,h*.5,p,duty,invhalf,half);c=k_sdirk(t+h*.5,half,n,h*.5,p,duty,invhalf,fine);}
  if(!(a&&b&&c)){k_jacobian(t,y,n,p,duty,jac);h*=.5;if(h<1e-12){rc=-1;rf=attempts;return;}continue;}
  double error=0.;for(int j=0;j<n;j++){if(j>=4&&j<=6)continue;double e=fabs(fine[j]-whole[j])/(3*(1e-7+tol*MAX(fabs(y[j]),fabs(fine[j]))));error=MAX(error,e);if(!isfinite(fine[j]))error=INFINITY;}
  if(error>1){h*=isfinite(error)?MAX(.15,.8*pow(error,-1./3)):.15;if(h<1e-12){rc=-1;rf=attempts;return;}continue;}
  t=end-t<=h?end:t+h;memcpy(y,fine,n*sizeof(double));if(!append_result(t,y,n))return;rf=attempts;
  if(y[0]<=.1){rc=3;return;}if(y[1]<-1e-8){rc=1;return;}if(y[1]>=(p[34]&&p[28]>=.5?30.:60.)){rc=4;return;}if(p[34]&&p[29]>=.5&&y[2]>=60){rc=5;return;}
  h=MIN(maxstep,h*(error<1e-12?2.:MIN(2.,MAX(.5,.85*pow(error,-1./3)))));
 }rf=attempts;rc=t>=end-1e-13?0:-1;
}
/* Summary state is packed as doubles; integer counts remain exact in this range. */
int k_waveform(const double *times,const double *values,int np,double period,int channels,int capacity,double *state){
 double *ix=state,*previous_time=ix+8,*previous=previous_time+1,*area=previous+channels,*low=area+channels,*high=low+channels,*valid=high+channels;
 double *ga=valid+channels,*gl=ga+channels,*gh=gl+channels,*gv=gh+channels,*means=gv+channels,*minima=means+capacity*channels,*maxima=minima+capacity*channels;
 double *starts=maxima+capacity*channels,*ends=starts+capacity,*counts=ends+capacity;
 for(int point=0;point<np;point++){double now=times[point],tol=MAX(period*1e-11,fabs(now)*4e-15);const double *v=values+point*channels;
  if(!ix[0]){double cycle=floor((now+tol)/period);ix[0]=1;ix[1]=cycle;ix[2]=fabs(now-cycle*period)>tol;previous_time[0]=now;memcpy(previous,v,channels*sizeof(double));continue;}
  double old=previous_time[0];if(now<old-tol)return 1;
  if(now<=old+tol){previous_time[0]=MAX(old,now);memcpy(previous,v,channels*sizeof(double));continue;}
  double left=old;while(left<now-tol){double boundary=(ix[1]+1)*period,right=MIN(now,boundary),width=right-left;
   if(width<0&&fabs(width)<=tol)width=0.;if(width<0)return 2;double f0=(left-old)/(now-old),f1=(right-old)/(now-old);
   for(int j=0;j<channels;j++){double a=previous[j],b=v[j];if(isfinite(a)&&isfinite(b)){double va=a+(b-a)*f0,vb=a+(b-a)*f1;area[j]+=.5*(va+vb)*width;low[j]=MIN(low[j],MIN(va,vb));high[j]=MAX(high[j],MAX(va,vb));}else if(width>0)valid[j]=0;}
   left=right;if(right>=boundary-tol){if(!ix[2]){if(ix[6]==0)ix[7]=ix[1];ix[3]++;ix[6]++;
    for(int j=0;j<channels;j++){ga[j]+=area[j];gl[j]=MIN(gl[j],low[j]);gh[j]=MAX(gh[j],high[j]);gv[j]=gv[j]&&valid[j];}
    if(ix[6]==ix[5]){int n=(int)ix[4];starts[n]=ix[7]*period;ends[n]=boundary;counts[n]=ix[6];
     for(int j=0;j<channels;j++){int pos=n*channels+j;means[pos]=gv[j]?ga[j]/(ix[6]*period):NAN;minima[pos]=gv[j]?gl[j]:NAN;maxima[pos]=gv[j]?gh[j]:NAN;ga[j]=0.;gl[j]=INFINITY;gh[j]=-INFINITY;gv[j]=1.;}
     ix[4]++;ix[6]=0;if(ix[4]==capacity){for(int k=0;k<capacity/2;k++){int a=2*k,b=a+1;
      for(int j=0;j<channels;j++){int at=a*channels+j,bt=b*channels+j,pos=k*channels+j;means[pos]=.5*(means[at]+means[bt]);minima[pos]=isfinite(means[pos])?MIN(minima[at],minima[bt]):NAN;maxima[pos]=isfinite(means[pos])?MAX(maxima[at],maxima[bt]):NAN;}
      starts[k]=starts[a];ends[k]=ends[b];counts[k]=counts[a]+counts[b];}ix[4]=capacity/2;ix[5]*=2;}}
   }ix[1]++;ix[2]=0;for(int j=0;j<channels;j++){area[j]=0.;low[j]=INFINITY;high[j]=-INFINITY;valid[j]=1.;}}
   else if(now-right<=tol)break;
  }previous_time[0]=now;memcpy(previous,v,channels*sizeof(double));
 }return 0;
}
