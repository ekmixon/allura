/*
       Licensed to the Apache Software Foundation (ASF) under one
       or more contributor license agreements.  See the NOTICE file
       distributed with this work for additional information
       regarding copyright ownership.  The ASF licenses this file
       to you under the Apache License, Version 2.0 (the
       "License"); you may not use this file except in compliance
       with the License.  You may obtain a copy of the License at

         http://www.apache.org/licenses/LICENSE-2.0

       Unless required by applicable law or agreed to in writing,
       software distributed under the License is distributed on an
       "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
       KIND, either express or implied.  See the License for the
       specific language governing permissions and limitations
       under the License.
*/

var dom = React.createElement;

/* top-level form state */
var state = {
  'thing': 'tool',
  'subscribed': false,
  'subscribed_to_tool': false,
  'url': '',
  'icon': {}
};

SubscriptionForm = React.createClass({

  getInitialState: function() {
    return {tooltip_timeout: null};
  },

  render: function() {
    var action = this.props.subscribed ? "Unsubscribe from" : "Subscribe to";
    var title = action + ' this ' + this.props.thing;
    var link_opts = {
      ref: 'link',
      className: this.props.subscribed ? 'active' : '',
      href: '#',
      title: title,
      onClick: this.handleClick
    };
    if (this.props.in_progress) {
      link_opts.style = {cursor: 'wait'};
    }
    var icon_opts = {
      'data-icon': this.props.icon.char,
      className: 'ico ' + this.props.icon.css,
      title: title
    };
    return dom('a', link_opts, dom('b', icon_opts));
  },

  handleClick: function() {
    var url = this.props.url;
    var csrf = $.cookie('_session_id');
    var data = {_session_id: csrf};
    if (this.props.subscribed) {
      data.unsubscribe = true;
    } else {
      data.subscribe = true;
    }
    set_state({in_progress: true});
    $.post(url, data, function(resp) {
      if (resp.status == 'ok') {
        set_state({
          subscribed: resp.subscribed,
          subscribed_to_tool: resp.subscribed_to_tool
        });
        var link = this.getLinkNode();
        var text = null;
        if (resp.subscribed_to_tool) {
          text = "You can't subscribe to this ";
          text += this.props.thing;
          text += " because you are already subscribed to the entire tool";
        } else {
          var action = resp.subscribed ? 'subscribed to' : 'unsubscribed from';
          text = 'Successfully ' + action + ' this ' + this.props.thing;
        }
        $(link).tooltipster('content', text).tooltipster('show');
        if (this.state.tooltip_timeout) {
          clearTimeout(this.state.tooltip_timeout);
        }
        var t = setTimeout(function() { $(link).tooltipster('hide'); }, 4000);
        this.setState({tooltip_timeout: t});
      }
    }.bind(this)).always(function() {
      set_state({in_progress: false});
    });
    return false;
  },

  getLinkNode: function() { return React.findDOMNode(this.refs.link); },

  componentDidMount: function() {
    var link = this.getLinkNode();
    $(link).tooltipster({
      content: '',
      animation: 'fade',
      delay: 200,
      trigger: 'custom',
      position: 'top',
      iconCloning: false,
      maxWidth: 300
    });
  }

});

function set_state(new_state) {
  /* Set state and re-render entire UI */
  for (var key in new_state) {
    state[key] = new_state[key];
  }
  render(state);
}

function render(state) {
  var props = {};
  for (var key in state) { props[key] = state[key]; }
  React.render(
    dom(SubscriptionForm, props),
    document.getElementById('subscription-form')
  );
}

$(function() {
  set_state(document.SUBSCRIPTION_OPTIONS);
});