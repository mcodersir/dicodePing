package ir.dicode.ping.ui

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import ir.dicode.ping.data.SourceDefinition
import ir.dicode.ping.databinding.ItemSourceBinding

class SourceAdapter(private val onEdit:(SourceDefinition)->Unit,private val onToggle:(SourceDefinition,Boolean)->Unit,private val onDelete:(SourceDefinition)->Unit,private val onMove:(SourceDefinition,Int)->Unit):RecyclerView.Adapter<SourceAdapter.H>(){
    var items:List<SourceDefinition> = emptyList();set(v){field=v;notifyDataSetChanged()}
    inner class H(val b:ItemSourceBinding):RecyclerView.ViewHolder(b.root)
    override fun onCreateViewHolder(p:ViewGroup,v:Int)=H(ItemSourceBinding.inflate(LayoutInflater.from(p.context),p,false))
    override fun getItemCount()=items.size
    override fun onBindViewHolder(h:H,pos:Int){val s=items[pos];with(h.b){name.text=s.name;url.text=s.url;enabled.setOnCheckedChangeListener(null);enabled.isChecked=s.enabled;enabled.isEnabled=!s.isDefault;delete.isEnabled=!s.isDefault;up.isEnabled=pos>0;down.isEnabled=pos<items.lastIndex;edit.setOnClickListener{onEdit(s)};enabled.setOnCheckedChangeListener{_,x->onToggle(s,x)};delete.setOnClickListener{onDelete(s)};up.setOnClickListener{onMove(s,-1)};down.setOnClickListener{onMove(s,1)}}}
}
