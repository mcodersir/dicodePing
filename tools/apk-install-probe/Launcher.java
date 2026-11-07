package ir.dicode.installprobe;
import android.app.Activity;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.content.*;
import android.database.*;
import android.net.Uri;
import java.io.*;
public class Launcher extends Activity {
 @Override public void onCreate(Bundle state) {
  super.onCreate(state);
  Intent request=new Intent(Intent.ACTION_INSTALL_PACKAGE);
  request.setDataAndType(Uri.parse("content://ir.dicode.installprobe.apk/package.apk"),"application/vnd.android.package-archive");
  request.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
  request.putExtra(Intent.EXTRA_RETURN_RESULT,true);
  startActivityForResult(request,1);
 }
 @Override protected void onActivityResult(int request,int result,Intent data) {
  super.onActivityResult(request,result,data);
  android.util.Log.i("InstallProbe","installer activity result="+result);
  finish();
 }
 public static class Files extends ContentProvider {
  public boolean onCreate(){return true;}
  public String getType(Uri uri){return "application/vnd.android.package-archive";}
  public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException {
   if(!"r".equals(mode)||!"/package.apk".equals(uri.getPath()))throw new FileNotFoundException();
   return ParcelFileDescriptor.open(new File(getContext().getFilesDir(),"package.apk"),ParcelFileDescriptor.MODE_READ_ONLY);
  }
  public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort) {
   File file=new File(getContext().getFilesDir(),"package.apk");
   String[] columns=projection!=null?projection:new String[]{"_display_name","_size"};
   MatrixCursor cursor=new MatrixCursor(columns);Object[] values=new Object[columns.length];
   for(int i=0;i<columns.length;i++)values[i]="_size".equals(columns[i])?Long.valueOf(file.length()):"DicodePing.apk";
   cursor.addRow(values);return cursor;
  }
  public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
  public int delete(Uri uri,String where,String[] args){throw new UnsupportedOperationException();}
  public int update(Uri uri,ContentValues values,String where,String[] args){throw new UnsupportedOperationException();}
 }
}
