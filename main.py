"""
    :copyright: (c) 2011 Local Projects, all rights reserved
    :license: Affero GNU GPL v3, see LEGAL/LICENSE for more details.
"""
from cdw import app
 
if __name__ == '__main__':
    app.run(host="0.0.0.0",port=app.config['HOST_PORT'])
